import asyncio
import aiohttp
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import logging
import json
import aiofiles

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class FastCrawler:
    def __init__(self, base_url, max_depth=5, max_concurrency=50, output_file="crawled_content.json"):
        self.base_url = base_url
        self.domain = urlparse(base_url).netloc
        self.max_depth = max_depth
        self.visited = set()
        self.headers = {'User-Agent': 'Mozilla/5.0'}
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.queue = asyncio.Queue()
        self.queue.put_nowait((self.base_url, 0))
        self.output_file = output_file
        self.crawled_data = {}

    async def fetch(self, session, url, depth):
        if depth > self.max_depth or url in self.visited:
            return

        parsed_url = urlparse(url)
        if parsed_url.netloc != self.domain:
            return

        self.visited.add(url)

        async with self.semaphore:
            try:
                async with session.get(url, headers=self.headers, timeout=15) as response:
                    if response.status != 200:
                        logger.warning(f"Failed to fetch {url}: HTTP {response.status}")
                        return

                    content_type = response.headers.get('Content-Type', '')
                    if 'text/html' not in content_type:
                        logger.info(f"Skipping non-HTML content at {url}")
                        return

                    content = await response.read()
                    try:
                        text = content.decode('utf-8')
                    except UnicodeDecodeError:
                        text = content.decode('utf-8', errors='replace')

                    logger.info(f"Depth {depth}: Successfully crawled: {url}")
                    self.crawled_data[url] = text
                    await self.parse_links(url, text, depth)
            except Exception as e:
                logger.error(f"Error fetching {url}: {e}")

    async def parse_links(self, url, content, depth):
        soup = BeautifulSoup(content, 'lxml')
        for link in soup.find_all('a', href=True):
            full_url = urljoin(url, link['href'])
            if urlparse(full_url).netloc == self.domain and full_url not in self.visited:
                await self.queue.put((full_url, depth + 1))

    async def crawl(self):
        connector = aiohttp.TCPConnector(limit_per_host=10)
        async with aiohttp.ClientSession(connector=connector) as session:
            tasks = []
            while True:
                if self.queue.empty():
                    if not tasks:
                        break
                    _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    tasks = list(pending)
                else:
                    url, depth = await self.queue.get()
                    task = asyncio.create_task(self.fetch(session, url, depth))
                    tasks.append(task)

            # Wait for remaining tasks to complete
            await asyncio.gather(*tasks)
            await self.write_to_file()
            return self.visited

    async def write_to_file(self):
        async with aiofiles.open(self.output_file, 'w', encoding='utf-8') as f:
            await f.write(json.dumps(self.crawled_data, ensure_ascii=False, indent=2))
        logger.info(f"Crawled content written to {self.output_file}")


async def main():
    base_url = "https://apidocs.bridge.xyz/"
    crawler = FastCrawler(base_url, max_depth=5, max_concurrency=50)
    logger.info(f"Starting crawl of {base_url}")
    urls = await crawler.crawl()

    print("\nCrawled URLs:")
    print("=" * 50)
    for i, url in enumerate(sorted(urls), 1):
        print(f"{i}. {url}")
    print(f"\nTotal URLs crawled: {len(urls)}")
    print(f"Crawled content saved to {crawler.output_file}")


if __name__ == "__main__":
    asyncio.run(main())
