import json
import re
from email.utils import parsedate_to_datetime
from pathlib import Path
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


if __name__ == '__main__':
    request = Request(FEED, headers={'User-Agent': 'NIA-SND-Portfolio-Sync/1.0'})
    with urlopen(request, timeout=20) as response:
        posts = portfolio_posts(response.read(2_000_000))
    path = Path('blog-portfolio.json')
    combined = {post['url']: post for post in posts}
    latest = sorted(combined.values(), key=lambda post: (post['date'], int(post['url'].rsplit('/', 1)[1])), reverse=True)
    path.write_text(json.dumps(latest[:6], ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
