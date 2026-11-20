import json
import re
from email.utils import parsedate_to_datetime
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from xml.etree import ElementTree

FEED = 'https://rss.blog.naver.com/nia_snd.xml'
CATEGORIES = {'portfolio', '시공사례', '포트폴리오'}


def portfolio_posts(payload):
    channel = ElementTree.fromstring(payload).find('./channel')
    if channel is None:
        raise ValueError('Missing RSS channel')

    posts = []
    for item in channel.findall('item'):
        categories = {re.sub(r'\s+', '', category.text or '').casefold()
                      for category in item.findall('category')}
        if not CATEGORIES.intersection(categories):
            continue
        link = (item.findtext('guid') or item.findtext('link') or '').strip()
        match = re.fullmatch(r'https://(?:m\.)?blog\.naver\.com/nia_snd/(\d+)(?:\?[^#]*)?', link)
        title = (item.findtext('title') or '').strip()
        if not match or not title:
            continue
        date = parsedate_to_datetime(item.findtext('pubDate')).date().isoformat()
        posts.append({'title': title, 'url': 'https://blog.naver.com/nia_snd/' + match[1], 'date': date})
    return posts


class ThumbnailParser(HTMLParser):
    image = None

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == 'meta' and values.get('property') == 'og:image':
            url = values.get('content', '')
            parsed = urlsplit(url)
            if parsed.scheme == 'https' and (parsed.hostname or '').endswith('.pstatic.net'):
                self.image = url


def thumbnail(url):
    request = Request(url.replace('https://blog.', 'https://m.blog.'), headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urlopen(request, timeout=12) as response:
            parser = ThumbnailParser()
            parser.feed(response.read(2_000_000).decode('utf-8', errors='replace'))
            return parser.image
    except (OSError, ValueError):
        return None


if __name__ == '__main__':
    request = Request(FEED, headers={'User-Agent': 'NIA-SND-Portfolio-Sync/1.0'})
    with urlopen(request, timeout=20) as response:
        posts = portfolio_posts(response.read(2_000_000))
    path = Path('blog-portfolio.json')
    combined = {post['url']: post for post in posts}
    latest = sorted(combined.values(), key=lambda post: (post['date'], int(post['url'].rsplit('/', 1)[1])), reverse=True)
    existing = {item['url']: item for item in json.loads(path.read_text())} if path.exists() else {}
    for post in latest[:6]:
        prior = existing.get(post['url'], {})
        for key in ('image', 'display_title', 'category'):
            if prior.get(key):
                post[key] = prior[key]
        if not post.get('image'):
            image = thumbnail(post['url'])
            if image:
                post['image'] = image
    path.write_text(json.dumps(latest[:6], ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
