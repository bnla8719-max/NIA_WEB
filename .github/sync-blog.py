import json
import re
from hashlib import sha256
from email.utils import parsedate_to_datetime
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from xml.etree import ElementTree

FEED = 'https://rss.blog.naver.com/nia_snd.xml'
CATEGORIES = {'portfolio', '시공사례', '포트폴리오'}
PROJECT_TYPES = (
    ('외부 사인', ('지주간판', '간판', '외부사인', '사인물')),
    ('스크린골프', ('스크린골프', '골프연습장')),
    ('커뮤니티', ('커뮤니티',)),
    ('사옥·오피스', ('사무실', '오피스', '사옥')),
    ('상업공간', ('상업공간', '매장', '카페')),
    ('주거공간', ('주거공간', '주택', '아파트')),
)
IMAGE_TYPES = {'image/jpeg': 'jpg', 'image/png': 'png', 'image/webp': 'webp', 'image/gif': 'gif'}
MAX_IMAGE_BYTES = 2_000_000
IMAGE_DIR = Path('assets/blog-portfolio')


def project_category(title):
    normalized = re.sub(r'\s+', '', title)
    for label, keywords in PROJECT_TYPES:
        if any(keyword in normalized for keyword in keywords):
            return label
    return '시공사례'


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
        posts.append({
            'title': title, 'url': 'https://blog.naver.com/nia_snd/' + match[1],
            'date': date, 'category': project_category(title),
        })
    return posts


def is_naver_image(url):
    parsed = urlsplit(url)
    return parsed.scheme == 'https' and (parsed.hostname or '').endswith('.pstatic.net')


class ThumbnailParser(HTMLParser):
    image = None

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == 'meta' and values.get('property') == 'og:image':
            url = values.get('content', '')
            if is_naver_image(url):
                self.image = url


def thumbnail(url):
    request = Request(url.replace('https://blog.', 'https://m.blog.'), headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urlopen(request, timeout=12) as response:
            parser = ThumbnailParser()
            parser.feed(response.read(2_000_000).decode('utf-8', errors='replace'))
        if not parser.image:
            return None
        request = Request(parser.image, headers={
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'https://m.blog.naver.com/',
        })
        with urlopen(request, timeout=12) as response:
            extension = IMAGE_TYPES.get(response.headers.get_content_type())
            if not extension or not is_naver_image(response.geturl()):
                return None
            image = response.read(MAX_IMAGE_BYTES + 1)
        if not image or len(image) > MAX_IMAGE_BYTES:
            return None
        post_id = url.rsplit('/', 1)[1]
        digest = sha256(image).hexdigest()[:12]
        path = IMAGE_DIR / f'{post_id}-{digest}.{extension}'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(image)
        return path.as_posix()
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
        if prior.get('display_title'):
            post['display_title'] = prior['display_title']
        image = thumbnail(post['url']) or prior.get('image')
        if image:
            post['image'] = image
    path.write_text(json.dumps(latest[:6], ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    current_images = {post.get('image') for post in latest[:6]}
    for image in IMAGE_DIR.glob('*'):
        if re.fullmatch(r'\d+-[0-9a-f]{12}\.(?:jpg|png|webp|gif)', image.name) and image.as_posix() not in current_images:
            image.unlink()
