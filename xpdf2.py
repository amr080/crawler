import asyncio
import aiohttp
from urllib.parse import urljoin, urlparse, urldefrag
import logging
import json
import re
from concurrent.futures import ThreadPoolExecutor
import tqdm

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class EnhancedDocFinder:
    def __init__(self, initial_url, max_depth=10, max_concurrency=200, output_file="document_links.json"):
        self.initial_url = initial_url
        self.base_url = None
        self.domain = None
        self.max_depth = max_depth
        self.visited = set()
        self.document_urls = set()
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.queue = asyncio.Queue()
        self.output_file = output_file
        self.executor = ThreadPoolExecutor(max_workers=20)
        self.pbar = None

    def clean_url(self, url):
        url = urldefrag(url)[0].rstrip('/')
        if url.startswith('//'):
            url = f"https:{url}"
        return url

    def is_same_domain(self, url):
        parsed_url = urlparse(url)
        return parsed_url.netloc == self.domain

    def is_document_link(self, url):
        document_patterns = [
            r'\.pdf$',
            r'docsend\.com',
            r'docs\.google\.com',
            r'dropbox\.com',
            r'box\.com',
            r'onedrive\.live\.com',
        ]
        return any(re.search(pattern, url, re.IGNORECASE) for pattern in document_patterns)

    async def detect_base_url(self, session):
        try:
            async with session.get(self.initial_url, headers=self.headers, allow_redirects=True) as response:
                final_url = str(response.url)
                self.base_url = f"{urlparse(final_url).scheme}://{urlparse(final_url).netloc}"
                self.domain = urlparse(self.base_url).netloc
                logger.info(f"Detected base URL: {self.base_url}")
                await self.queue.put((self.base_url, 0))
        except Exception as e:
            logger.error(f"Error detecting base URL: {e}")
            raise

    async def fetch(self, session, url, depth):
        if depth > self.max_depth or url in self.visited:
            return

        await self.semaphore.acquire()
        try:
            async with session.get(url, headers=self.headers, timeout=30, allow_redirects=True) as response:
                if response.status != 200:
                    logger.warning(f"Failed to fetch {url}: HTTP {response.status}")
                    return
                content = await response.text()
                self.visited.add(url)
                logger.info(f"Depth {depth}: Successfully fetched: {url}")
                await self.parse_links(url, content, depth)
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
        finally:
            self.semaphore.release()
            self.pbar.update(1)

    async def parse_links(self, url, content, depth):
        link_patterns = [
            r'href=[\'"]?([^\'" >]+)',
            r'src=[\'"]?([^\'" >]+)',
            r'[\'"](/[^\'"\s]+|https?://[^\'"\s]+)[\'"]'
        ]

        all_links = []
        for pattern in link_patterns:
            all_links.extend(re.findall(pattern, content))

        for link in all_links:
            full_url = urljoin(url, link)
            full_url = self.clean_url(full_url)
            if self.is_document_link(full_url):
                self.document_urls.add(full_url)
                logger.info(f"Found document link: {full_url}")
            elif self.is_same_domain(full_url) and full_url not in self.visited:
                await self.queue.put((full_url, depth + 1))

    async def find_documents(self):
        connector = aiohttp.TCPConnector(limit_per_host=100, ssl=False)
        async with aiohttp.ClientSession(connector=connector) as session:
            await self.detect_base_url(session)

            self.pbar = tqdm.tqdm(total=self.max_depth * 100, desc="Crawling Progress")
            tasks = []
            while True:
                if self.queue.empty():
                    if not tasks:
                        break
                    _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    tasks = list(pending)
                else:
                    url, depth = await self.queue.get()
                    if url not in self.visited and self.is_same_domain(url):
                        task = asyncio.create_task(self.fetch(session, url, depth))
                        tasks.append(task)

        self.pbar.close()
        await self.write_to_file()
        return self.document_urls

    async def write_to_file(self):
        def write():
            with open(self.output_file, 'w', encoding='utf-8') as f:
                json.dump(list(self.document_urls), f, ensure_ascii=False, indent=2)

        await asyncio.get_event_loop().run_in_executor(self.executor, write)
        logger.info(f"Document URLs written to {self.output_file}")


async def main():
    initial_url = "https://ondo.finance/"
    finder = EnhancedDocFinder(initial_url, max_depth=10, max_concurrency=200)
    logger.info(f"Starting document search from {initial_url}")
    docs = await finder.find_documents()

    print("\nFound Document URLs:")
    print("=" * 50)
    for i, url in enumerate(sorted(docs), 1):
        print(f"{i}. {url}")
    print(f"\nTotal documents found: {len(docs)}")
    print(f"Document URLs saved to {finder.output_file}")


if __name__ == "__main__":
    asyncio.run(main())