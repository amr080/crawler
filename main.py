import asyncio
import aiohttp
from urllib.parse import urljoin, urlparse, urldefrag
import logging
import json
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class EnhancedURLFinder:
    def __init__(self, base_url, max_depth=10, max_concurrency=200, output_file="all_urls.json"):
        self.base_url = base_url
        self.domain = urlparse(base_url).netloc
        self.max_depth = max_depth
        self.visited = set()
        self.all_urls = set()
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.queue = asyncio.Queue()
        self.queue.put_nowait((self.base_url, 0))
        self.output_file = output_file

    def clean_url(self, url):
        # Remove fragments and trailing slashes
        url = urldefrag(url)[0].rstrip('/')
        # Handle relative URLs
        if url.startswith('//'):
            url = f"https:{url}"
        return url

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

    async def parse_links(self, url, content, depth):
        # Find href links
        href_links = re.findall(r'href=[\'"]?([^\'" >]+)', content)
        # Find src links
        src_links = re.findall(r'src=[\'"]?([^\'" >]+)', content)
        # Find data-href links
        data_href_links = re.findall(r'data-href=[\'"]?([^\'" >]+)', content)
        # Find onclick links
        onclick_links = re.findall(r'onclick=[\'"]?window\.location\.href=[\'"](.*?)[\'"]', content)
        # Find URLs in JavaScript
        js_links = re.findall(r'[\'"](/[^\'"\s]+|https?://[^\'"\s]+)[\'"]', content)

        all_links = href_links + src_links + data_href_links + onclick_links + js_links

        for link in all_links:
            full_url = urljoin(url, link)
            full_url = self.clean_url(full_url)
            parsed_url = urlparse(full_url)
            if parsed_url.netloc == self.domain:
                self.all_urls.add(full_url)
                if full_url not in self.visited:
                    await self.queue.put((full_url, depth + 1))

    async def find_urls(self):
        connector = aiohttp.TCPConnector(limit_per_host=100, ssl=False)
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
                    if url not in self.visited:
                        task = asyncio.create_task(self.fetch(session, url, depth))
                        tasks.append(task)

        self.write_to_file()
        return self.all_urls

    def write_to_file(self):
        with open(self.output_file, 'w', encoding='utf-8') as f:
            json.dump(list(self.all_urls), f, ensure_ascii=False, indent=2)
        logger.info(f"All URLs written to {self.output_file}")


async def main():
    base_url = "https://ondo.finance/"
    finder = EnhancedURLFinder(base_url, max_depth=10, max_concurrency=200)
    logger.info(f"Starting enhanced URL search on {base_url}")
    urls = await finder.find_urls()

    print("\nAll Found URLs:")
    print("=" * 50)
    for i, url in enumerate(sorted(urls), 1):
        print(f"{i}. {url}")
    print(f"\nTotal URLs found: {len(urls)}")
    print(f"URLs saved to {finder.output_file}")


if __name__ == "__main__":
    asyncio.run(main())