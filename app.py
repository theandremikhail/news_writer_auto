import streamlit as st
import feedparser
import requests
from bs4 import BeautifulSoup
import anthropic
import datetime
import hashlib
import time
import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse, urljoin
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from PIL import Image
from supabase import create_client, Client
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ============= CONFIGURATION =============
class ClickMovementConfig:
    WORDPRESS_SITES = {
        "american_conservatives": {
            "name": "American Conservatives",
            "wp_url": "https://americanconservatives.com",
            "username": st.secrets.get("ac_username", ""),
            "password": st.secrets.get("ac_password", ""),
            "writer_style": "Ben Shapiro",
            "style_description": "Fast-paced, fact-driven with sharp logical reasoning",
            "themes": ["conservative", "politics", "freedom", "economy", "breaking"],
            "target_audience": "Conservative Americans",
            "newsletter_brands": ["American Conservative AM", "American Conservative PM"]
        },
        "americans_digest": {
            "name": "The American's Digest",
            "wp_url": "https://theamericansdigest.com",
            "username": st.secrets.get("ad_username", ""),
            "password": st.secrets.get("ad_password", ""),
            "writer_style": "Walter Cronkite",
            "style_description": "Authoritative, measured, and trustworthy delivery",
            "themes": ["national", "politics", "economy", "culture", "conservative", "breaking"],
            "target_audience": "Mainstream conservatives",
            "newsletter_brands": ["Americans Daily Digest"]
        },
        "conservatives_daily": {
            "name": "Conservatives Daily",
            "wp_url": "https://conservativesdaily.com",
            "username": st.secrets.get("cd_username", ""),
            "password": st.secrets.get("cd_password", ""),
            "writer_style": "Dan Rather",
            "style_description": "Folksy yet authoritative, with investigative edge",
            "themes": ["breaking", "daily", "conservative", "america", "trending"],
            "target_audience": "Daily conservative readers",
            "newsletter_brands": ["Conservatives Daily AM", "Conservatives Daily PM"]
        },
        "world_reports": {
            "name": "World Reports",
            "wp_url": "https://worldlyreports.com",
            "username": st.secrets.get("wr_username", ""),
            "password": st.secrets.get("wr_password", ""),
            "writer_style": "Walter Cronkite",
            "style_description": "Global perspective with American viewpoint",
            "themes": ["world", "international", "global", "foreign", "breaking"],
            "target_audience": "Internationally-aware conservatives",
            "newsletter_brands": ["Worldly Reports AM", "Worldly Reports PM"]
        }
    }

    NEWS_SOURCES = {
        "breaking": [
            {"name": "Reuters", "rss": "https://feeds.reuters.com/reuters/topNews", "weight": 5},
            {"name": "AP Breaking", "rss": "https://feeds.apnews.com/rss/apf-topnews", "weight": 5},
            {"name": "CNN Breaking", "rss": "http://rss.cnn.com/rss/cnn_latest.rss", "weight": 5},
            {"name": "BBC Breaking", "rss": "http://feeds.bbci.co.uk/news/world/rss.xml", "weight": 5},
        ],
        "conservative": [
            {"name": "Newsmax", "rss": "https://www.newsmax.com/rss/Newsfront/16/", "weight": 4},
            {"name": "Fox News", "rss": "http://feeds.foxnews.com/foxnews/latest", "weight": 4},
            {"name": "Fox Politics", "rss": "http://feeds.foxnews.com/foxnews/politics", "weight": 4},
            {"name": "Daily Wire", "rss": "https://www.dailywire.com/feeds/rss.xml", "weight": 3},
            {"name": "Breitbart", "rss": "https://feeds.feedburner.com/breitbart", "weight": 3},
            {"name": "PJ Media", "rss": "https://pjmedia.com/feed", "weight": 3},
            {"name": "Federalist", "rss": "https://thefederalist.com/feed/", "weight": 3},
            {"name": "RedState", "rss": "https://redstate.com/feed", "weight": 2},
            {"name": "Townhall", "rss": "https://townhall.com/rss", "weight": 2},
            {"name": "Daily Caller", "rss": "https://dailycaller.com/feed/", "weight": 2},
        ],
        "mainstream": [
            {"name": "Reuters", "rss": "https://feeds.reuters.com/reuters/topNews", "weight": 5},
            {"name": "AP News", "rss": "https://feeds.apnews.com/rss/apf-topnews", "weight": 5},
            {"name": "CBS", "rss": "https://www.cbsnews.com/latest/rss/main", "weight": 4},
            {"name": "NBC", "rss": "https://feeds.nbcnews.com/nbcnews/public/news", "weight": 4},
            {"name": "ABC News", "rss": "https://feeds.abcnews.com/abcnews/topstories", "weight": 4},
            {"name": "USA Today", "rss": "http://rssfeeds.usatoday.com/usatoday-NewsTopStories", "weight": 3},
        ],
        "world": [
            {"name": "BBC World", "rss": "http://feeds.bbci.co.uk/news/world/rss.xml", "weight": 5},
            {"name": "Guardian World", "rss": "https://www.theguardian.com/world/rss", "weight": 4},
            {"name": "Reuters World", "rss": "https://feeds.reuters.com/Reuters/worldNews", "weight": 5},
        ],
        "politics": [
            {"name": "Politico", "rss": "https://www.politico.com/rss/politicopicks.xml", "weight": 4},
            {"name": "The Hill", "rss": "https://thehill.com/feed/", "weight": 4},
        ]
    }

    MIN_WORDS = 350
    MAX_WORDS = 800
    ARTICLES_PER_SITE = 10
    ANTHROPIC_KEY = st.secrets.get("anthropic_key", "")
    SUPABASE_URL = st.secrets.get("supabase_url", "")
    SUPABASE_KEY = st.secrets.get("supabase_key", "")

# ============= SUPABASE DATABASE =============
class SupabaseDatabase:
    def __init__(self):
        if ClickMovementConfig.SUPABASE_URL and ClickMovementConfig.SUPABASE_KEY:
            self.client: Client = create_client(
                ClickMovementConfig.SUPABASE_URL,
                ClickMovementConfig.SUPABASE_KEY
            )
        else:
            self.client = None
            st.warning("Supabase not configured. Features disabled.")

    def is_duplicate(self, url: str, content: str, site: str) -> bool:
        """Check if article is duplicate by URL or similar content"""
        if not self.client:
            return False

        try:
            url_hash = hashlib.md5(url.encode()).hexdigest()
            content_hash = hashlib.md5(content[:1000].encode()).hexdigest()

            url_check = self.client.table('processed_articles').select('id').eq('url_hash', url_hash).execute()
            if url_check.data:
                return True

            content_check = self.client.table('processed_articles').select('id').eq('content_hash', content_hash).eq('site', site).execute()
            if content_check.data:
                return True

            return False
        except Exception as e:
            return False

    def add_processed(self, url: str, content: str, title: str, site: str, wordpress_post_id: Optional[int] = None):
        """Add processed article to database"""
        if not self.client:
            return

        try:
            url_hash = hashlib.md5(url.encode()).hexdigest()
            content_hash = hashlib.md5(content[:1000].encode()).hexdigest()

            self.client.table('processed_articles').insert({
                'url_hash': url_hash,
                'content_hash': content_hash,
                'title': title,
                'site': site,
                'wordpress_post_id': wordpress_post_id
            }).execute()
        except Exception as e:
            pass

    def add_newsletter_metrics(self, platform: str, date: str, brand: str,
                               campaign_type: Optional[str], metrics: Dict):
        """Store newsletter performance metrics"""
        if not self.client:
            return

        try:
            self.client.table('newsletter_metrics').upsert({
                'date': date,
                'brand': brand,
                'platform': platform,
                'campaign_type': campaign_type,
                'sends': metrics.get('sends', 0),
                'delivered': metrics.get('delivered', 0.0),
                'opens': metrics.get('opens', 0),
                'open_rate': metrics.get('open_rate', 0.0),
                'unique_opens': metrics.get('unique_opens', 0),
                'unique_open_rate': metrics.get('unique_open_rate', 0.0),
                'clicks': metrics.get('clicks', 0),
                'ctr': metrics.get('ctr', 0.0),
                'unique_clicks': metrics.get('unique_clicks', 0),
                'uctr': metrics.get('uctr', 0.0),
                'brand_list_size': metrics.get('list_size', 0),
                'list_growth': metrics.get('list_growth', 0),
                'unsubscribes': metrics.get('unsubscribes', 0),
                'unsubscribe_rate': metrics.get('unsubscribe_rate', 0.0),
                'spam_reports': metrics.get('spam', 0)
            }, on_conflict='date,brand,campaign_type').execute()
        except Exception as e:
            st.error(f"Failed to store metrics: {str(e)}")

    def get_newsletter_metrics(self, days: int = 30, platform: Optional[str] = None,
                                brand: Optional[str] = None) -> pd.DataFrame:
        """Get newsletter metrics with filters"""
        if not self.client:
            return pd.DataFrame()

        try:
            cutoff_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

            query = self.client.table('newsletter_metrics')\
                .select('*')\
                .gte('date', cutoff_date)\
                .order('date', desc=True)

            if platform:
                query = query.eq('platform', platform)
            if brand:
                query = query.eq('brand', brand)

            response = query.execute()

            if response.data:
                return pd.DataFrame(response.data)
            return pd.DataFrame()
        except Exception as e:
            st.error(f"Failed to fetch metrics: {str(e)}")
            return pd.DataFrame()

    def get_brand_list(self) -> List[Dict]:
        """Get list of configured brands"""
        if not self.client:
            return []

        try:
            response = self.client.table('newsletter_brands')\
                .select('*')\
                .eq('active', True)\
                .order('display_order')\
                .execute()

            return response.data if response.data else []
        except Exception as e:
            return []

    def link_article_to_newsletter(self, wordpress_post_id: int, article_title: str,
                                    brands_sent_to: List[str]):
        """Link published article to newsletter brands"""
        if not self.client:
            return

        try:
            self.client.table('article_newsletter_performance').insert({
                'wordpress_post_id': wordpress_post_id,
                'article_title': article_title,
                'date_sent': datetime.now().strftime('%Y-%m-%d'),
                'brands_sent_to': brands_sent_to
            }).execute()
        except Exception as e:
            pass

# ============= NEWS FETCHER =============
class NewsFetcher:
    def fetch_articles(self, themes: List[str], limit: int = 50) -> List[Dict]:
        all_articles = []
        categories = self._get_categories(themes)

        us_sources = ['Reuters', 'AP Breaking', 'AP News', 'Fox News', 'Fox Politics',
                      'Newsmax', 'CNN Breaking', 'CBS', 'NBC', 'ABC News', 'USA Today',
                      'Daily Wire', 'Breitbart', 'PJ Media', 'Federalist', 'RedState',
                      'Townhall', 'Daily Caller', 'Politico', 'The Hill']

        for category in categories:
            for source in ClickMovementConfig.NEWS_SOURCES.get(category, []):
                try:
                    feed = feedparser.parse(source['rss'])
                    for entry in feed.entries[:20]:
                        weight = source['weight']
                        if source['name'] in us_sources:
                            weight *= 3

                        all_articles.append({
                            'title': entry.get('title', ''),
                            'link': entry.get('link', ''),
                            'summary': entry.get('summary', ''),
                            'source': source['name'],
                            'score': self._score(entry, themes, weight),
                            'is_us': source['name'] in us_sources
                        })
                except:
                    continue

        all_articles.sort(key=lambda x: x['score'], reverse=True)
        return all_articles[:limit]

    def _get_categories(self, themes):
        cats = set()
        for theme in themes:
            if theme in ["conservative", "freedom", "america"]:
                cats.add("conservative")
            if theme in ["breaking", "daily", "trending"]:
                cats.add("breaking")
            if theme in ["politics", "economy"]:
                cats.update(["politics", "mainstream"])
            if theme in ["world", "international", "global", "foreign"]:
                cats.add("world")
            if theme in ["national", "top", "culture"]:
                cats.add("mainstream")
        return cats or {"breaking", "mainstream", "conservative"}

    def _score(self, entry, themes, weight):
        score = weight * 10
        text = f"{entry.get('title', '')} {entry.get('summary', '')}".lower()

        for theme in themes:
            if theme.lower() in text:
                score += 25

        us_keywords = ['america', 'us ', 'u.s.', 'united states', 'washington', 'congress',
                      'senate', 'house', 'trump', 'biden', 'republican', 'democrat',
                      'border', 'immigration', 'texas', 'california', 'florida']

        for keyword in us_keywords:
            if keyword in text:
                score += 15

        return score

# ============= CONTENT PROCESSOR =============
class ContentProcessor:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=ClickMovementConfig.ANTHROPIC_KEY) if ClickMovementConfig.ANTHROPIC_KEY else None

    def scrape_article(self, url: str) -> str:
        try:
            response = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
            soup = BeautifulSoup(response.content, 'html.parser')

            for element in soup(['script', 'style', 'nav', 'header', 'footer']):
                element.decompose()

            selectors = ['article', '.article-body', '.entry-content', '.post-content', 'main']
            for selector in selectors:
                elements = soup.select(selector)
                if elements:
                    paragraphs = elements[0].find_all(['p'])
                    text = ' '.join([p.get_text(strip=True) for p in paragraphs])
                    if len(text) > 500:
                        return self._deep_clean(text)

            paragraphs = soup.find_all('p')
            text = ' '.join([p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 50])
            return self._deep_clean(text)
        except:
            return ""

    def _deep_clean(self, text: str) -> str:
        if not text:
            return ""

        junk_patterns = [
            r'[A-Z][a-z]+\s+[A-Z][a-z]+\s+is\s+a\s+(?:reporter|writer|correspondent).*',
            r'Story tips can be sent to.*',
            r'CLICK HERE TO.*',
            r'Subscribe.*newsletter.*',
            r'Follow.*on.*',
            r'@[\w]+',
            r'\s*\d{4}.*',
            r'All [Rr]ights [Rr]eserved',
        ]

        for pattern in junk_patterns:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)

        sources = ['Fox News', 'CNN', 'MSNBC', 'Reuters', 'AP', 'BBC']
        for source in sources:
            text = re.sub(rf'\b{source}\b', '', text, flags=re.IGNORECASE)

        lines = []
        for line in text.split('\n'):
            line = line.strip()
            if not line or len(line) < 20:
                continue
            if any(x in line.lower() for x in ['click here', 'subscribe', 'follow', 'contact']):
                continue
            lines.append(line)

        return ' '.join(lines).strip()

    def rewrite_article(self, content: str, site_config: Dict) -> Tuple[str, List[str]]:
        if not self.client or not content:
            return "", []

        prompt = f"""Rewrite this news article following the TONE and PERSPECTIVE of {site_config['writer_style']}.

CRITICAL RULES:
- NO author bios or bylines
- NO source names (Fox News, CNN, etc)
- NO subscription text
- NO "click here" or navigation
- NO social media handles
- NO copyright notices
- Write as {site_config['name']} original reporting
- Use PROPER GRAMMAR throughout (no mimicking speaking patterns)
- Follow the TONE: {site_config['style_description']}
- Maintain journalistic professionalism

TONE GUIDELINES:
- Ben Shapiro tone: Fast-paced, fact-driven, sharp logical reasoning (but proper grammar)
- Walter Cronkite tone: Authoritative, measured, trustworthy delivery (but proper grammar)
- Dan Rather tone: Folksy yet authoritative, investigative edge (but proper grammar)

Target Audience: {site_config['target_audience']}
Length: {ClickMovementConfig.MIN_WORDS}-{ClickMovementConfig.MAX_WORDS} words

Article to rewrite:
{content[:3000]}

Generate 3 headline options and the rewritten article.

HEADLINE REQUIREMENTS:
- Write natural, straightforward headlines
- NO colons or "Title: Subtitle" format
- NO "EXCLUSIVE:" or "BREAKING:" prefixes
- Just clear, direct headlines
- Example: "Trump Administration Announces New Education Policy"
- NOT: "Education Reform: Trump Administration Takes Bold Action"

Format:
HEADLINES:
1. [headline]
2. [headline]
3. [headline]

ARTICLE:
[rewritten content]
"""

        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=3000,
                temperature=0.7,
                messages=[{"role": "user", "content": prompt}]
            )

            text = response.content[0].text

            headlines = []
            article = ""

            if "HEADLINES:" in text and "ARTICLE:" in text:
                parts = text.split("ARTICLE:")
                headline_section = parts[0].replace("HEADLINES:", "").strip()
                article = parts[1].strip()

                for line in headline_section.split('\n'):
                    line = re.sub(r'^\d+\.\s*', '', line).strip()
                    line = line.strip('"').strip("'")
                    if line and len(line) > 10:
                        headlines.append(line)

            return article, headlines[:3]
        except Exception as e:
            st.error(f"Rewrite error: {str(e)}")
            return "", []

# ============= IMAGE FETCHER =============
class ImageFetcher:
    def fetch_images(self, url: str) -> List[str]:
        try:
            response = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
            soup = BeautifulSoup(response.content, 'html.parser')

            images = []

            for tag in soup.find_all('meta', property='og:image'):
                img_url = tag.get('content')
                if img_url and self._is_valid_image(img_url):
                    images.append(urljoin(url, img_url))

            for tag in soup.find_all('meta', attrs={'name': 'twitter:image'}):
                img_url = tag.get('content')
                if img_url and self._is_valid_image(img_url):
                    images.append(urljoin(url, img_url))

            for img in soup.select('article img, .article-body img, .entry-content img')[:15]:
                src = img.get('data-src') or img.get('src')
                if src and self._is_valid_image(src):
                    images.append(urljoin(url, src))

            seen = set()
            unique_images = []
            for img in images:
                if img not in seen:
                    seen.add(img)
                    unique_images.append(img)

            return unique_images[:12]
        except Exception as e:
            return []

    def _is_valid_image(self, url: str) -> bool:
        if not url:
            return False
        url_lower = url.lower()
        invalid_terms = ['logo', 'icon', 'avatar', 'profile', 'badge', 'pixel', '1x1', 'tracking']
        if any(term in url_lower for term in invalid_terms):
            return False
        valid_extensions = ['.jpg', '.jpeg', '.png', '.webp']
        return any(ext in url_lower for ext in valid_extensions) or 'image' in url_lower

    def resize_image(self, image_url: str) -> Optional[BytesIO]:
        try:
            response = requests.get(image_url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
            if response.status_code != 200:
                return None

            img = Image.open(BytesIO(response.content))

            if img.mode in ('RGBA', 'LA', 'P'):
                img = img.convert('RGB')

            target_width = 860
            target_height = 475

            img_aspect = img.width / img.height
            target_aspect = target_width / target_height

            if img_aspect > target_aspect:
                new_height = target_height
                new_width = int(target_height * img_aspect)
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                left = (new_width - target_width) // 2
                img = img.crop((left, 0, left + target_width, target_height))
            else:
                new_width = target_width
                new_height = int(target_width / img_aspect)
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                top = (new_height - target_height) // 2
                img = img.crop((0, top, target_width, top + target_height))

            output = BytesIO()
            img.save(output, format='JPEG', quality=90)
            output.seek(0)
            return output

        except Exception as e:
            return None

# ============= WORDPRESS PUBLISHER =============
class WordPressPublisher:
    def __init__(self):
        self.sessions = {}

    def _get_session(self, site_config: Dict) -> requests.Session:
        site_key = site_config['name']

        if site_key not in self.sessions:
            session = requests.Session()
            session.auth = (site_config['username'], site_config['password'])
            session.headers.update({
                'Content-Type': 'application/json',
                'User-Agent': 'WordPress-Python-Client/1.0',
                'Accept': 'application/json'
            })
            self.sessions[site_key] = session

        return self.sessions[site_key]

    def test_connection(self, site_config: Dict) -> Dict:
        try:
            session = self._get_session(site_config)
            api_url = f"{site_config['wp_url']}/wp-json/wp/v2/users/me"

            response = session.get(api_url, timeout=10)

            if response.status_code == 200:
                user_data = response.json()
                return {
                    'success': True,
                    'message': f'Connected as {user_data.get("name", "Unknown")}',
                    'user': user_data
                }
            elif response.status_code == 401:
                return {
                    'success': False,
                    'error': 'Authentication failed. Check username/password or create Application Password in WordPress Users > Profile.'
                }
            elif response.status_code == 403:
                return {
                    'success': False,
                    'error': 'REST API is blocked. Check security plugins (Wordfence, iThemes) or server firewall.'
                }
            else:
                return {
                    'success': False,
                    'error': f'Status {response.status_code}: {response.text[:200]}'
                }

        except Exception as e:
            return {'success': False, 'error': f'Connection error: {str(e)}'}

    def get_recent_posts(self, site_config: Dict, limit: int = 10) -> List[Dict]:
        try:
            session = self._get_session(site_config)
            seven_days_ago = (datetime.now() - timedelta(days=7)).isoformat()

            api_url = f"{site_config['wp_url']}/wp-json/wp/v2/posts"
            response = session.get(
                api_url,
                params={
                    'per_page': limit,
                    'after': seven_days_ago,
                    'status': 'publish',
                    'orderby': 'date',
                    'order': 'desc'
                },
                timeout=10
            )

            if response.status_code == 200:
                posts = response.json()
                return [{'title': p['title']['rendered'], 'link': p['link']} for p in posts]

            return []
        except Exception as e:
            return []

    def add_internal_link(self, content: str, site_config: Dict) -> str:
        recent_posts = self.get_recent_posts(site_config, limit=5)

        if not recent_posts:
            return content

        import random
        post = random.choice(recent_posts)

        internal_link = f'\n\n<p><strong>Related:</strong> <a href="{post["link"]}">{post["title"]}</a></p>'
        return content + internal_link

    def publish(self, site_config: Dict, title: str, content: str, status: str = 'draft',
                image_url: Optional[str] = None, tags: Optional[List[str]] = None) -> Dict:
        try:
            session = self._get_session(site_config)
            api_url = f"{site_config['wp_url']}/wp-json/wp/v2/posts"

            content_with_link = self.add_internal_link(content, site_config)

            content_cleaned = re.sub(r'<h1>.*?</h1>', '', content_with_link, flags=re.IGNORECASE)

            if '<p>' not in content_cleaned:
                paragraphs = [p.strip() for p in content_cleaned.split('\n\n') if p.strip()]
                content_cleaned = ''.join(f'<p>{p}</p>' for p in paragraphs)

            content_cleaned = re.sub(r'<p>\s*</p>', '', content_cleaned)

            payload = {
                'title': title,
                'content': content_cleaned,
                'status': status
            }

            featured_media_id = None
            if image_url:
                featured_media_id = self._upload_image(site_config, image_url, title)
                if featured_media_id:
                    payload['featured_media'] = featured_media_id

            tag_ids = []
            if tags:
                tag_ids = self._get_or_create_tags(site_config, tags)
                if tag_ids:
                    payload['tags'] = tag_ids

            response = session.post(api_url, json=payload, timeout=30)

            if response.status_code == 201:
                post_id = response.json()['id']
                return {
                    'success': True,
                    'post_id': post_id,
                    'edit_url': f"{site_config['wp_url']}/wp-admin/post.php?post={post_id}&action=edit",
                    'featured_image_set': featured_media_id is not None,
                    'tags_set': len(tag_ids),
                    'internal_link_added': True
                }
            elif response.status_code == 401:
                return {
                    'success': False,
                    'error': 'Authentication failed. Check your Application Password in WordPress Users > Profile.'
                }
            elif response.status_code == 403:
                return {
                    'success': False,
                    'error': 'Access forbidden. Possible causes: REST API disabled, security plugin blocking, or insufficient user permissions.'
                }
            elif response.status_code == 400:
                error_data = response.json()
                return {
                    'success': False,
                    'error': f'Invalid parameters: {error_data.get("message", "WordPress rejected the post content")}'
                }
            else:
                return {
                    'success': False,
                    'error': f'Status {response.status_code}: {response.text[:500]}'
                }
        except Exception as e:
            return {'success': False, 'error': f'Error: {str(e)}'}

    def _upload_image(self, site_config: Dict, image_url: str, title: str) -> Optional[int]:
        try:
            session = self._get_session(site_config)

            image_fetcher = ImageFetcher()
            resized_image = image_fetcher.resize_image(image_url)

            if not resized_image:
                return None

            media_url = f"{site_config['wp_url']}/wp-json/wp/v2/media"

            files = {
                'file': ('featured-image.jpg', resized_image, 'image/jpeg')
            }

            upload_session = requests.Session()
            upload_session.auth = session.auth
            upload_session.headers.update({
                'User-Agent': 'WordPress-Python-Client/1.0'
            })

            response = upload_session.post(
                media_url,
                files=files,
                data={'title': title[:100], 'alt_text': title[:100]},
                timeout=30
            )

            if response.status_code == 201:
                return response.json()['id']

            return None

        except Exception as e:
            return None

    def _get_or_create_tags(self, site_config: Dict, tag_names: List[str]) -> List[int]:
        try:
            session = self._get_session(site_config)
            tags_url = f"{site_config['wp_url']}/wp-json/wp/v2/tags"
            tag_ids = []

            for tag_name in tag_names[:5]:
                search_response = session.get(
                    tags_url,
                    params={'search': tag_name},
                    timeout=10
                )

                if search_response.status_code == 200:
                    tags = search_response.json()
                    if tags:
                        tag_ids.append(tags[0]['id'])
                        continue

                create_response = session.post(
                    tags_url,
                    json={'name': tag_name},
                    timeout=10
                )

                if create_response.status_code == 201:
                    tag_ids.append(create_response.json()['id'])

            return tag_ids

        except Exception as e:
            return []

# ============= MAIN PROCESSOR =============
class NewsProcessor:
    def __init__(self):
        self.db = SupabaseDatabase()
        self.fetcher = NewsFetcher()
        self.processor = ContentProcessor()
        self.images = ImageFetcher()
        self.publisher = WordPressPublisher()
        self.used_urls = set()

    def _generate_tags(self, article_title: str, content: str, site_config: Dict) -> List[str]:
        tags = []

        theme_tags = {
            'conservative': 'Conservative',
            'politics': 'Politics',
            'economy': 'Economy',
            'breaking': 'Breaking News',
            'world': 'World News',
            'international': 'International',
            'culture': 'Culture',
            'national': 'National News',
            'freedom': 'Freedom',
            'america': 'America'
        }

        for theme in site_config.get('themes', []):
            if theme in theme_tags:
                tags.append(theme_tags[theme])

        title_lower = article_title.lower()
        keyword_map = {
            'trump': 'Donald Trump',
            'biden': 'Joe Biden',
            'election': 'Election',
            'border': 'Border Security',
            'immigration': 'Immigration',
            'tax': 'Tax Policy',
            'crime': 'Crime',
            'gun': 'Second Amendment',
            'abortion': 'Pro-Life',
            'china': 'China',
            'russia': 'Russia',
            'ukraine': 'Ukraine',
            'israel': 'Israel',
            'middle east': 'Middle East',
            'supreme court': 'Supreme Court',
            'congress': 'Congress',
            'senate': 'Senate'
        }

        for keyword, tag in keyword_map.items():
            if keyword in title_lower and tag not in tags:
                tags.append(tag)

        return tags[:5]

    def process_articles_global(self, num_articles: int = 40) -> List[Dict]:
        processed = []

        all_themes = set()
        for site_config in ClickMovementConfig.WORDPRESS_SITES.values():
            all_themes.update(site_config['themes'])

        articles = self.fetcher.fetch_articles(list(all_themes), limit=num_articles * 5)

        for article in articles:
            if len(processed) >= num_articles:
                break

            if article['link'] in self.used_urls:
                continue

            # Scrape but DON'T rewrite yet - store raw content
            full_content = self.processor.scrape_article(article['link'])
            if not full_content or len(full_content.split()) < 150:
                continue

            is_dup = False
            for site_key in ClickMovementConfig.WORDPRESS_SITES.keys():
                if self.db.is_duplicate(article['link'], full_content, site_key):
                    is_dup = True
                    break

            if is_dup:
                continue

            image_urls = self.images.fetch_images(article['link'])

            processed.append({
                'original_title': article['title'],
                'raw_content': full_content,  # Store raw, not rewritten
                'source': article['source'],
                'url': article['link'],
                'images': image_urls,
                'image_page': 0,
                'word_count': len(full_content.split()),
                'is_us_source': article.get('is_us', False),
                'rewrites': {}  # Will store {site_key: {'content': ..., 'headlines': ...}}
            })

            self.used_urls.add(article['link'])

        return processed

# ============= DASHBOARD FUNCTIONS =============
def show_google_sheets_view():
    """Exact replica of Google Sheets table"""
    st.markdown("## Google Sheets View")

    db = SupabaseDatabase()

    if not db.client:
        st.error("Supabase not configured.")
        return

    # Filters
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        days = st.selectbox("Date Range", [7, 14, 30, 60, 90], index=2, key="sheets_days")
    with col2:
        platform_filter = st.selectbox("Platform", ["All", "tinyemail", "beehiiv"], key="sheets_platform")
    with col3:
        brands = db.get_brand_list()
        brand_names = ["All"] + [b['brand_name'] for b in brands]
        brand_filter = st.selectbox("Brand", brand_names, key="sheets_brand")
    with col4:
        if st.button("Refresh", use_container_width=True):
            st.rerun()

    # Fetch data
    platform = None if platform_filter == "All" else platform_filter
    brand = None if brand_filter == "All" else brand_filter

    df = db.get_newsletter_metrics(days=days, platform=platform, brand=brand)

    if df.empty:
        st.info("No data available. Use Tab 3 to add test data or import historical data.")
        return

    # Format the dataframe to match Google Sheets exactly
    display_df = df[['date', 'brand', 'sends', 'delivered', 'opens', 'open_rate',
                     'unique_opens', 'unique_open_rate', 'clicks', 'ctr',
                     'unique_clicks', 'uctr', 'brand_list_size', 'list_growth',
                     'unsubscribe_rate', 'unsubscribes', 'spam_reports']].copy()

    display_df.columns = ['Date', 'Brand', 'Sends', 'Delivered', 'Opens', 'Open Rate',
                          'Unique Opens', 'Unique Open Rate', 'Clicks', 'CTR',
                          'Unique Clicks', 'UCTR', 'Brand List Size', 'List Growth',
                          '% Unsubscribe', 'Unsubscribes', 'Spam']

    # Apply styling - black background for rows with Sends = 0
    def style_row(row):
        if row['Sends'] == 0:
            return ['background-color: black; color: white'] * len(row)
        return [''] * len(row)

    styled_df = display_df.style.apply(style_row, axis=1)

    st.dataframe(styled_df, use_container_width=True, height=600)

    # Export options
    col1, col2 = st.columns(2)
    with col1:
        csv = display_df.to_csv(index=False)
        st.download_button(
            "Download CSV",
            csv,
            f"newsletter_data_{datetime.now().strftime('%Y%m%d')}.csv",
            "text/csv",
            use_container_width=True
        )
    with col2:
        st.info(f"Showing {len(display_df)} records")

def show_analytics_dashboard():
    """Enhanced analytics with charts"""
    st.markdown("## Analytics Dashboard")

    db = SupabaseDatabase()

    if not db.client:
        st.error("Supabase not configured.")
        return

    # Filters
    col1, col2 = st.columns(2)
    with col1:
        days = st.selectbox("Time Period", [7, 14, 30, 60, 90], index=2, key="analytics_days")
    with col2:
        auto_refresh = st.toggle("Auto-Refresh (30s)", value=False, key="analytics_refresh")

    if auto_refresh:
        st.markdown(f"""
        <meta http-equiv="refresh" content="30">
        """, unsafe_allow_html=True)
        st.caption("Live - Refreshing every 30 seconds")

    df = db.get_newsletter_metrics(days=days)

    if df.empty:
        st.info("No data available.")
        return

    # KPIs
    st.markdown("### Key Metrics")

    total_sends = df['sends'].sum()
    avg_open_rate = df[df['sends'] > 0]['open_rate'].mean()
    avg_ctr = df[df['sends'] > 0]['ctr'].mean()
    total_growth = df['list_growth'].sum()

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Sends", f"{total_sends:,}")
    with col2:
        st.metric("Avg Open Rate", f"{avg_open_rate:.1f}%")
    with col3:
        st.metric("Avg CTR", f"{avg_ctr:.2f}%")
    with col4:
        st.metric("List Growth", f"{total_growth:+,}")

    # Charts
    st.markdown("### Trends")

    # Open Rate Trends
    fig1 = px.line(df, x='date', y='open_rate', color='brand',
                   title='Open Rate Trends',
                   labels={'open_rate': 'Open Rate (%)', 'date': 'Date'})
    st.plotly_chart(fig1, use_container_width=True)

    # CTR Comparison
    brand_avg = df[df['sends'] > 0].groupby('brand').agg({
        'ctr': 'mean',
        'open_rate': 'mean',
        'sends': 'sum'
    }).reset_index()

    fig2 = px.bar(brand_avg, x='brand', y='ctr',
                  title='Average CTR by Brand',
                  labels={'ctr': 'CTR (%)', 'brand': 'Brand'})
    st.plotly_chart(fig2, use_container_width=True)

    # Performance Heatmap
    st.markdown("### Performance Heatmap")

    # Pivot for heatmap
    heatmap_data = df.pivot_table(values='open_rate', index='brand', columns='date', aggfunc='mean')

    fig3 = px.imshow(heatmap_data,
                     labels=dict(x="Date", y="Brand", color="Open Rate %"),
                     title="Open Rate Heatmap",
                     color_continuous_scale='RdYlGn',
                     aspect="auto")
    st.plotly_chart(fig3, use_container_width=True)

    # Top Performers
    st.markdown("### Top Performing Days")

    top_days = df.nlargest(10, 'open_rate')[['date', 'brand', 'sends', 'open_rate', 'ctr']]
    st.dataframe(top_days, use_container_width=True)

# ============= STREAMLIT UI =============
st.set_page_config(page_title="News Intelligence Platform", layout="wide", page_icon="📰")

if 'processed_articles' not in st.session_state:
    st.session_state.processed_articles = []
if 'published' not in st.session_state:
    st.session_state.published = set()
if 'article_rewrites' not in st.session_state:
    st.session_state.article_rewrites = {}

st.markdown("""
<style>
    .header {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
        padding: 2rem;
        border-radius: 10px;
        margin-bottom: 2rem;
    }
    .header h1 {
        color: white;
        margin: 0;
        font-size: 2.5rem;
        font-weight: 300;
    }
    .article-card {
        background: white;
        border: 1px solid #e0e0e0;
        border-radius: 8px;
        padding: 2rem;
        margin: 1.5rem 0;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    .stat-box {
        background: #f5f5f5;
        padding: 1rem;
        border-radius: 6px;
        text-align: center;
    }
    .preview-box {
        background: #f9f9f9;
        border-left: 4px solid #4CAF50;
        padding: 1rem;
        margin: 0.5rem 0;
        border-radius: 4px;
    }
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="header"><h1>News Intelligence Platform</h1></div>', unsafe_allow_html=True)

# Main Navigation
tab1, tab2, tab3 = st.tabs(["Article Publishing", "Newsletter Performance", "Data Management"])

with tab1:
    st.markdown("## Article Publishing")

    with st.expander("How Dynamic Writing Styles Work"):
        st.markdown("""
        **Dynamic Rewriting System:**
        - Articles are initially scraped (no rewrite yet)
        - When you check a site, the article is rewritten in that site's unique voice
        - Preview each version before publishing
        - Compare versions side-by-side

        **Writing Styles:**
        - **Ben Shapiro** (American Conservatives): Fast-paced, fact-driven, sharp reasoning
        - **Walter Cronkite** (The American's Digest, World Reports): Authoritative, measured, trustworthy
        - **Dan Rather** (Conservatives Daily): Folksy yet authoritative, investigative edge
        """)

    # Controls
    col1, col2, col3, col4 = st.columns([1.5, 1.5, 1.5, 1])

    with col1:
        num_articles = st.number_input("Number of Articles", min_value=10, max_value=50, value=40, step=5)

    with col2:
        if st.button("Fetch Articles", type="primary", use_container_width=True):
            processor = NewsProcessor()

            with st.spinner(f"Fetching {num_articles} articles..."):
                articles = processor.process_articles_global(num_articles)
                st.session_state.processed_articles = articles
                st.session_state.article_rewrites = {}
                st.success(f"Fetched {len(articles)} articles!")
                st.rerun()

    with col3:
        if st.button("Test Connections", use_container_width=True):
            publisher = WordPressPublisher()
            for site_key, site_config in ClickMovementConfig.WORDPRESS_SITES.items():
                result = publisher.test_connection(site_config)
                if result['success']:
                    st.success(f"OK {site_config['name']}: {result['message']}")
                else:
                    st.error(f"FAIL {site_config['name']}: {result['error']}")

    with col4:
        if st.button("Clear All", use_container_width=True):
            st.session_state.processed_articles = []
            st.session_state.published = set()
            st.session_state.article_rewrites = {}
            st.rerun()

    # Display articles
    if st.session_state.processed_articles:
        total = len(st.session_state.processed_articles)
        published = len(st.session_state.published)
        us_count = sum(1 for a in st.session_state.processed_articles if a.get('is_us_source', False))

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.markdown(f'<div class="stat-box"><h2>{total}</h2><p>Total Articles</p></div>', unsafe_allow_html=True)
        with col2:
            st.markdown(f'<div class="stat-box"><h2>{published}</h2><p>Published</p></div>', unsafe_allow_html=True)
        with col3:
            st.markdown(f'<div class="stat-box"><h2>{total-published}</h2><p>Ready</p></div>', unsafe_allow_html=True)
        with col4:
            st.markdown(f'<div class="stat-box"><h2>US {us_count}</h2><p>US Sources</p></div>', unsafe_allow_html=True)

        st.markdown("---")

        for idx, article in enumerate(st.session_state.processed_articles):
            article_id = f"article_{idx}"

            with st.container():
                st.markdown('<div class="article-card">', unsafe_allow_html=True)

                st.markdown(f"### {article['original_title']}")

                us_badge = "US " if article.get('is_us_source', False) else "INTL "
                st.caption(f"{us_badge}Source: {article['source']} | Words: ~{article['word_count']}")

                # Site selection with dynamic rewriting
                st.write("**Select Sites to Publish:**")

                selected_sites = []
                site_cols = st.columns(4)

                for idx_site, (site_key, site_config) in enumerate(ClickMovementConfig.WORDPRESS_SITES.items()):
                    with site_cols[idx_site]:
                        # Checkbox for site selection
                        is_selected = st.checkbox(
                            f"{site_config['name']}",
                            key=f"{article_id}_site_{site_key}",
                            disabled=article_id in st.session_state.published
                        )

                        if is_selected:
                            selected_sites.append((site_key, site_config))

                            # Check if already rewritten
                            if idx not in st.session_state.article_rewrites:
                                st.session_state.article_rewrites[idx] = {}

                            if site_key not in st.session_state.article_rewrites[idx]:
                                # Rewrite in this site's style
                                with st.spinner(f"Rewriting in {site_config['writer_style']} style..."):
                                    processor = ContentProcessor()
                                    content, headlines = processor.rewrite_article(
                                        article['raw_content'],
                                        site_config
                                    )

                                    if content and headlines:
                                        st.session_state.article_rewrites[idx][site_key] = {
                                            'content': content,
                                            'headlines': headlines,
                                            'tags': NewsProcessor()._generate_tags(
                                                article['original_title'],
                                                content,
                                                site_config
                                            )
                                        }
                                        st.success(f"OK {site_config['writer_style']} version ready")
                                        st.rerun()
                            else:
                                st.caption(f"OK {site_config['writer_style']} style")

                if not selected_sites and article_id not in st.session_state.published:
                    st.warning("Select at least one site to publish")

                # Show previews for selected sites
                if selected_sites and idx in st.session_state.article_rewrites:
                    st.markdown("**Preview Versions:**")

                    for site_key, site_config in selected_sites:
                        if site_key in st.session_state.article_rewrites[idx]:
                            rewrite_data = st.session_state.article_rewrites[idx][site_key]

                            with st.expander(f"{site_config['name']} ({site_config['writer_style']} style)"):
                                # Headline selector
                                selected_headline = st.selectbox(
                                    "Select Headline",
                                    rewrite_data['headlines'],
                                    key=f"headline_{article_id}_{site_key}"
                                )

                                # Preview first 300 characters
                                preview_text = rewrite_data['content'][:300] + "..."
                                st.markdown(f'<div class="preview-box">{preview_text}</div>', unsafe_allow_html=True)

                                # Full article toggle
                                if st.checkbox("Show Full Article", key=f"full_{article_id}_{site_key}"):
                                    st.write(rewrite_data['content'])

                                # Tags
                                if rewrite_data.get('tags'):
                                    st.caption(f"**Tags:** {', '.join(rewrite_data['tags'])}")

                # Image selection
                if article['images']:
                    col_prev, col_img_sel, col_next = st.columns([0.5, 3, 0.5])

                    with col_prev:
                        st.write("")
                        st.write("")
                        if st.button("<", key=f"prev_img_{article_id}", use_container_width=True):
                            if article['image_page'] > 0:
                                st.session_state.processed_articles[idx]['image_page'] -= 1
                                st.rerun()

                    with col_img_sel:
                        page = article.get('image_page', 0)
                        start_idx = page * 3
                        end_idx = min(start_idx + 3, len(article['images']))
                        visible_images = article['images'][start_idx:end_idx]

                        if visible_images:
                            image_options = ["No Featured Image"] + [f"Image {start_idx + i + 1}" for i in range(len(visible_images))]
                            selected_image_idx = st.selectbox(
                                f"Featured Image (Page {page + 1}/{(len(article['images']) - 1) // 3 + 1})",
                                range(len(image_options)),
                                format_func=lambda x: image_options[x],
                                key=f"image_{article_id}",
                                index=1 if visible_images else 0
                            )

                            selected_image = visible_images[selected_image_idx - 1] if selected_image_idx > 0 else None
                        else:
                            selected_image = None

                    with col_next:
                        st.write("")
                        st.write("")
                        max_page = (len(article['images']) - 1) // 3
                        if st.button(">", key=f"next_img_{article_id}", use_container_width=True):
                            if article.get('image_page', 0) < max_page:
                                st.session_state.processed_articles[idx]['image_page'] += 1
                                st.rerun()

                    # Display images
                    if visible_images:
                        img_cols = st.columns(min(3, len(visible_images)))
                        for img_idx, img_url in enumerate(visible_images):
                            with img_cols[img_idx]:
                                try:
                                    response = requests.get(img_url, timeout=5, headers={'User-Agent': 'Mozilla/5.0'})
                                    img = Image.open(BytesIO(response.content))
                                    st.image(img, use_container_width=True)
                                    st.caption(f"Image {start_idx + img_idx + 1}")
                                except:
                                    st.warning(f"Image failed")
                else:
                    selected_image = None

                # Publish buttons
                if selected_sites and article_id not in st.session_state.published:
                    col1, col2, col3 = st.columns(3)

                    with col1:
                        if st.button(f"Publish Draft ({len(selected_sites)} sites)",
                                   key=f"draft_{article_id}",
                                   use_container_width=True):
                            publisher = WordPressPublisher()
                            processor = NewsProcessor()

                            for site_key, site_config in selected_sites:
                                if site_key in st.session_state.article_rewrites[idx]:
                                    rewrite_data = st.session_state.article_rewrites[idx][site_key]

                                    # Get selected headline for this site
                                    headline_key = f"headline_{article_id}_{site_key}"
                                    if headline_key in st.session_state:
                                        selected_headline = st.session_state[headline_key]
                                    else:
                                        selected_headline = rewrite_data['headlines'][0]

                                    result = publisher.publish(
                                        site_config,
                                        selected_headline,
                                        rewrite_data['content'],
                                        'draft',
                                        image_url=selected_image,
                                        tags=rewrite_data.get('tags', [])
                                    )

                                    if result['success']:
                                        processor.db.add_processed(
                                            article['url'],
                                            rewrite_data['content'],
                                            article['original_title'],
                                            site_key,
                                            wordpress_post_id=result.get('post_id')
                                        )

                                        # Link to newsletter
                                        processor.db.link_article_to_newsletter(
                                            result['post_id'],
                                            selected_headline,
                                            site_config.get('newsletter_brands', [])
                                        )

                                        st.success(f"OK {site_config['name']}: [Edit]({result['edit_url']})")
                                    else:
                                        st.error(f"FAIL {site_config['name']}: {result['error']}")

                            st.session_state.published.add(article_id)
                            time.sleep(2)
                            st.rerun()

                    with col2:
                        if st.button(f"Publish Live ({len(selected_sites)} sites)",
                                   key=f"live_{article_id}",
                                   type="primary",
                                   use_container_width=True):
                            publisher = WordPressPublisher()
                            processor = NewsProcessor()

                            for site_key, site_config in selected_sites:
                                if site_key in st.session_state.article_rewrites[idx]:
                                    rewrite_data = st.session_state.article_rewrites[idx][site_key]

                                    headline_key = f"headline_{article_id}_{site_key}"
                                    if headline_key in st.session_state:
                                        selected_headline = st.session_state[headline_key]
                                    else:
                                        selected_headline = rewrite_data['headlines'][0]

                                    result = publisher.publish(
                                        site_config,
                                        selected_headline,
                                        rewrite_data['content'],
                                        'publish',
                                        image_url=selected_image,
                                        tags=rewrite_data.get('tags', [])
                                    )

                                    if result['success']:
                                        processor.db.add_processed(
                                            article['url'],
                                            rewrite_data['content'],
                                            article['original_title'],
                                            site_key,
                                            wordpress_post_id=result.get('post_id')
                                        )

                                        processor.db.link_article_to_newsletter(
                                            result['post_id'],
                                            selected_headline,
                                            site_config.get('newsletter_brands', [])
                                        )

                                        st.success(f"OK {site_config['name']}: [View]({result['edit_url']})")
                                    else:
                                        st.error(f"FAIL {site_config['name']}: {result['error']}")

                            st.session_state.published.add(article_id)
                            st.balloons()
                            time.sleep(2)
                            st.rerun()

                    with col3:
                        st.link_button("View Source", article['url'], use_container_width=True)

                elif article_id in st.session_state.published:
                    st.success("Published")

                st.markdown('</div>', unsafe_allow_html=True)
                st.markdown("---")

    else:
        st.info("Click 'Fetch Articles' to begin")

with tab2:
    sub_tab1, sub_tab2 = st.tabs(["Google Sheets View", "KPI Dashboard"])

    with sub_tab1:
        show_google_sheets_view()

    with sub_tab2:
        st.markdown("## Newsletter KPI Dashboard")

        # ============= HELPER FUNCTIONS =============
        def get_metrics_for_period(start_date, end_date, platform=None, brands=None):
            """Get aggregated metrics for a date range with flexible brand filtering"""
            try:
                db = SupabaseDatabase()
                if not db.client:
                    return None

                query = db.client.table('newsletter_metrics').select('*')
                query = query.gte('date', start_date.strftime('%Y-%m-%d')).lte('date', end_date.strftime('%Y-%m-%d'))

                if platform:
                    query = query.eq('platform', platform)

                result = query.execute()

                if not result.data:
                    return None

                df = pd.DataFrame(result.data)

                # Filter by brands if specified
                if brands and len(brands) > 0:
                    df = df[df['brand'].isin(brands)]

                if df.empty:
                    return None

                df['delivered_count'] = (df['sends'] * df['delivered'] / 100).fillna(0).astype(int)

                # Calculate average rates (weighted by sends)
                total_sends = df['sends'].sum()
                if total_sends > 0:
                    avg_open_rate = (df['opens'].sum() / total_sends * 100) if total_sends > 0 else 0
                    avg_ctr = (df['clicks'].sum() / total_sends * 100) if total_sends > 0 else 0
                    avg_unique_open_rate = (df['unique_opens'].sum() / total_sends * 100) if total_sends > 0 else 0
                    avg_uctr = (df['unique_clicks'].sum() / total_sends * 100) if total_sends > 0 else 0
                else:
                    avg_open_rate = avg_ctr = avg_unique_open_rate = avg_uctr = 0

                return {
                    'sends': int(df['sends'].sum()),
                    'delivered': int(df['delivered_count'].sum()),
                    'opens': int(df['opens'].sum()),
                    'unique_opens': int(df['unique_opens'].sum()),
                    'clicks': int(df['clicks'].sum()),
                    'unique_clicks': int(df['unique_clicks'].sum()),
                    'spam_reports': int(df['spam_reports'].sum()),
                    'unsubscribes': int(df['unsubscribes'].sum()),
                    'list_size': int(df['brand_list_size'].max()) if len(df) > 0 else 0,
                    'list_growth': int(df['list_growth'].sum()),
                    'open_rate': round(avg_open_rate, 2),
                    'ctr': round(avg_ctr, 2),
                    'unique_open_rate': round(avg_unique_open_rate, 2),
                    'uctr': round(avg_uctr, 2),
                    'records': len(df)
                }
            except Exception as e:
                st.error(f"Error: {e}")
                return None

        def calculate_pct_change(current, previous):
            """Calculate percentage change"""
            if previous == 0:
                return 0.0
            return round(((current - previous) / previous) * 100, 1)

        def get_week_bounds(week_offset=0):
            """Get start and end dates for a week (Monday to Sunday)"""
            today = datetime.now().date()
            # Find the most recent Monday
            days_since_monday = today.weekday()
            current_week_start = today - timedelta(days=days_since_monday)
            # Apply offset (negative = past weeks)
            week_start = current_week_start + timedelta(weeks=week_offset)
            week_end = week_start + timedelta(days=6)
            return week_start, week_end

        def get_month_bounds(month_offset=0):
            """Get start and end dates for a month"""
            today = datetime.now().date()
            # Calculate target month
            year = today.year
            month = today.month + month_offset

            while month < 1:
                month += 12
                year -= 1
            while month > 12:
                month -= 12
                year += 1

            month_start = today.replace(year=year, month=month, day=1)

            # Get last day of month
            if month == 12:
                next_month = month_start.replace(year=year + 1, month=1)
            else:
                next_month = month_start.replace(month=month + 1)
            month_end = next_month - timedelta(days=1)

            return month_start, month_end

        def get_available_brands():
            """Get list of all available brands from database"""
            try:
                db = SupabaseDatabase()
                if not db.client:
                    return []

                result = db.client.table('newsletter_metrics').select('brand').execute()
                if result.data:
                    brands = list(set([r['brand'] for r in result.data]))
                    return sorted(brands)
                return []
            except:
                return []

        def get_base_brand_name(brand):
            """Extract base brand name without AM/PM suffix"""
            return brand.replace(' AM', '').replace(' PM', '').strip()

        def get_combined_brand_options(brands):
            """Generate combined brand options (AM+PM)"""
            base_brands = set()
            for brand in brands:
                base = get_base_brand_name(brand)
                base_brands.add(base)
            return sorted(list(base_brands))

        # ============= DATA SOURCE SELECTION =============
        st.markdown("### Data Source")

        available_brands = get_available_brands()
        combined_brands = get_combined_brand_options(available_brands)

        col1, col2 = st.columns(2)

        with col1:
            data_source_type = st.selectbox(
                "View Data By",
                ["Specific Newsletter", "Combined Newsletter (AM + PM)", "Platform", "All Data"],
                key="kpi_data_source_type"
            )

        with col2:
            selected_brands = []
            selected_platform = None
            display_title = "All Newsletters"

            if data_source_type == "Specific Newsletter":
                selected_newsletter = st.selectbox(
                    "Select Newsletter",
                    available_brands if available_brands else ["No data available"],
                    key="kpi_specific_newsletter"
                )
                if selected_newsletter and selected_newsletter != "No data available":
                    selected_brands = [selected_newsletter]
                    display_title = selected_newsletter

            elif data_source_type == "Combined Newsletter (AM + PM)":
                selected_combined = st.selectbox(
                    "Select Newsletter Brand",
                    combined_brands if combined_brands else ["No data available"],
                    key="kpi_combined_newsletter"
                )
                if selected_combined and selected_combined != "No data available":
                    # Find all variants (AM, PM, or base name)
                    selected_brands = [b for b in available_brands if get_base_brand_name(b) == selected_combined]
                    display_title = f"{selected_combined} (Combined AM + PM)"

            elif data_source_type == "Platform":
                selected_platform = st.selectbox(
                    "Select Platform",
                    ["TinyEmail", "Beehiiv"],
                    key="kpi_platform"
                )
                display_title = f"{selected_platform} (All Newsletters)"

            else:  # All Data
                display_title = "All Newsletters (Combined)"

        st.markdown("---")

        # ============= COMPARISON MODE SELECTION =============
        st.markdown("### Comparison Mode")

        comparison_mode = st.radio(
            "Compare By",
            ["Daily", "Weekly", "Monthly"],
            horizontal=True,
            key="kpi_comparison_mode"
        )

        today = datetime.now().date()

        if comparison_mode == "Daily":
            col1, col2 = st.columns(2)
            with col1:
                current_date = st.date_input(
                    "Current Date",
                    value=today - timedelta(days=1),
                    key="kpi_current_date"
                )
            with col2:
                compare_date = st.date_input(
                    "Compare To Date",
                    value=today - timedelta(days=2),
                    key="kpi_compare_date"
                )

            current_start = current_end = current_date
            compare_start = compare_end = compare_date
            period_label = "Daily"
            current_label = current_date.strftime('%b %d, %Y')
            compare_label = compare_date.strftime('%b %d, %Y')

        elif comparison_mode == "Weekly":
            # Generate week options (last 12 weeks)
            week_options = []
            for i in range(12):
                start, end = get_week_bounds(-i)
                label = f"{start.strftime('%b %d')} - {end.strftime('%b %d, %Y')}"
                week_options.append((label, -i))

            col1, col2 = st.columns(2)
            with col1:
                current_week_idx = st.selectbox(
                    "Current Week",
                    range(len(week_options)),
                    format_func=lambda x: week_options[x][0],
                    index=0,
                    key="kpi_current_week"
                )
            with col2:
                compare_week_idx = st.selectbox(
                    "Compare To Week",
                    range(len(week_options)),
                    format_func=lambda x: week_options[x][0],
                    index=1,
                    key="kpi_compare_week"
                )

            current_start, current_end = get_week_bounds(week_options[current_week_idx][1])
            compare_start, compare_end = get_week_bounds(week_options[compare_week_idx][1])
            period_label = "Weekly"
            current_label = week_options[current_week_idx][0]
            compare_label = week_options[compare_week_idx][0]

        else:  # Monthly
            # Generate month options (last 12 months)
            month_options = []
            for i in range(12):
                start, end = get_month_bounds(-i)
                label = start.strftime('%B %Y')
                month_options.append((label, -i))

            col1, col2 = st.columns(2)
            with col1:
                current_month_idx = st.selectbox(
                    "Current Month",
                    range(len(month_options)),
                    format_func=lambda x: month_options[x][0],
                    index=0,
                    key="kpi_current_month"
                )
            with col2:
                compare_month_idx = st.selectbox(
                    "Compare To Month",
                    range(len(month_options)),
                    format_func=lambda x: month_options[x][0],
                    index=1,
                    key="kpi_compare_month"
                )

            current_start, current_end = get_month_bounds(month_options[current_month_idx][1])
            compare_start, compare_end = get_month_bounds(month_options[compare_month_idx][1])
            period_label = "Monthly"
            current_label = month_options[current_month_idx][0]
            compare_label = month_options[compare_month_idx][0]

        st.markdown("---")

        # ============= FETCH AND DISPLAY DATA =============
        st.markdown(f"### {display_title}")
        st.caption(f"Comparing: **{current_label}** vs **{compare_label}**")

        # Fetch metrics
        current_metrics = get_metrics_for_period(
            current_start, current_end,
            platform=selected_platform,
            brands=selected_brands if selected_brands else None
        )

        compare_metrics = get_metrics_for_period(
            compare_start, compare_end,
            platform=selected_platform,
            brands=selected_brands if selected_brands else None
        )

        if not current_metrics and not compare_metrics:
            st.info("No data available for the selected filters and date range.")
        else:
            # Display KPI cards
            col1, col2, col3, col4 = st.columns(4)

            with col1:
                current_sends = current_metrics.get('sends', 0) if current_metrics else 0
                compare_sends = compare_metrics.get('sends', 0) if compare_metrics else 0
                delta = calculate_pct_change(current_sends, compare_sends)
                st.metric(
                    "Total Sends",
                    f"{current_sends:,}",
                    delta=f"{delta:+.1f}%" if compare_sends > 0 else None
                )

            with col2:
                current_opens = current_metrics.get('open_rate', 0) if current_metrics else 0
                compare_opens = compare_metrics.get('open_rate', 0) if compare_metrics else 0
                delta = current_opens - compare_opens
                st.metric(
                    "Open Rate",
                    f"{current_opens:.1f}%",
                    delta=f"{delta:+.1f}%" if compare_opens > 0 else None
                )

            with col3:
                current_ctr = current_metrics.get('ctr', 0) if current_metrics else 0
                compare_ctr = compare_metrics.get('ctr', 0) if compare_metrics else 0
                delta = current_ctr - compare_ctr
                st.metric(
                    "Click Rate",
                    f"{current_ctr:.2f}%",
                    delta=f"{delta:+.2f}%" if compare_ctr > 0 else None
                )

            with col4:
                current_growth = current_metrics.get('list_growth', 0) if current_metrics else 0
                compare_growth = compare_metrics.get('list_growth', 0) if compare_metrics else 0
                st.metric(
                    "List Growth",
                    f"{current_growth:+,}",
                    delta=f"{current_growth - compare_growth:+,}" if compare_growth != 0 else None
                )

            st.markdown("---")

            # Detailed metrics table
            st.markdown("### Detailed Metrics")

            metrics_config = [
                ('Sends', 'sends', 'count'),
                ('Delivered', 'delivered', 'count'),
                ('Opens', 'opens', 'count'),
                ('Open Rate', 'open_rate', 'percent'),
                ('Unique Opens', 'unique_opens', 'count'),
                ('Unique Open Rate', 'unique_open_rate', 'percent'),
                ('Clicks', 'clicks', 'count'),
                ('CTR', 'ctr', 'percent'),
                ('Unique Clicks', 'unique_clicks', 'count'),
                ('Unique CTR', 'uctr', 'percent'),
                ('Unsubscribes', 'unsubscribes', 'count'),
                ('Spam Reports', 'spam_reports', 'count'),
                ('List Growth', 'list_growth', 'count'),
            ]

            # Table header
            cols = st.columns([3, 2, 2, 2])
            with cols[0]:
                st.markdown("**Metric**")
            with cols[1]:
                st.markdown(f"**{current_label}**")
            with cols[2]:
                st.markdown(f"**{compare_label}**")
            with cols[3]:
                st.markdown("**Change**")

            st.markdown("---")

            for label, key, fmt in metrics_config:
                cols = st.columns([3, 2, 2, 2])

                current_val = current_metrics.get(key, 0) if current_metrics else 0
                compare_val = compare_metrics.get(key, 0) if compare_metrics else 0

                if fmt == 'percent':
                    current_display = f"{current_val:.2f}%"
                    compare_display = f"{compare_val:.2f}%"
                    change = current_val - compare_val
                    change_display = f"{change:+.2f}%"
                else:
                    current_display = f"{current_val:,}"
                    compare_display = f"{compare_val:,}"
                    if compare_val != 0:
                        change_pct = calculate_pct_change(current_val, compare_val)
                        change_display = f"{change_pct:+.1f}%"
                    else:
                        change_display = "N/A"

                with cols[0]:
                    st.markdown(f"**{label}**")
                with cols[1]:
                    st.markdown(current_display)
                with cols[2]:
                    st.markdown(compare_display)
                with cols[3]:
                    st.markdown(change_display)

        st.markdown("---")

        # ============= BRAND GROWTH SUMMARY =============
        st.markdown("### Brand Growth Summary")

        try:
            db = SupabaseDatabase()
            if db.client:
                query = db.client.table('newsletter_metrics').select('*')
                query = query.gte('date', (today - timedelta(days=90)).strftime('%Y-%m-%d'))
                result = query.execute()

                if result.data:
                    df = pd.DataFrame(result.data)
                    df['date'] = pd.to_datetime(df['date']).dt.date

                    brands = df['brand'].unique()

                    brand_data = []
                    for brand in sorted(brands):
                        brand_df = df[df['brand'] == brand].sort_values('date')

                        if len(brand_df) == 0:
                            continue

                        latest_record = brand_df.iloc[-1]
                        list_size = int(latest_record['brand_list_size'])
                        latest_date = latest_record['date']

                        week_ago_date = latest_date - timedelta(days=7)
                        week_ago_df = brand_df[brand_df['date'] <= week_ago_date]

                        if len(week_ago_df) > 0:
                            week_ago_size = int(week_ago_df.iloc[-1]['brand_list_size'])
                            week_growth = list_size - week_ago_size
                            week_growth_pct = (week_growth / week_ago_size * 100) if week_ago_size > 0 else 0
                        else:
                            week_growth = 0
                            week_growth_pct = 0

                        month_ago_date = latest_date - timedelta(days=30)
                        month_ago_df = brand_df[brand_df['date'] <= month_ago_date]

                        if len(month_ago_df) > 0:
                            month_ago_size = int(month_ago_df.iloc[-1]['brand_list_size'])
                            month_growth = list_size - month_ago_size
                            month_growth_pct = (month_growth / month_ago_size * 100) if month_ago_size > 0 else 0
                        else:
                            month_growth = 0
                            month_growth_pct = 0

                        brand_data.append({
                            'Brand': brand,
                            'Active List Size': f"{list_size:,}",
                            'Week over Week': f"{week_growth:+,} ({week_growth_pct:+.1f}%)",
                            'Month over Month': f"{month_growth:+,} ({month_growth_pct:+.1f}%)",
                            'Last Updated': latest_date.strftime('%b %d')
                        })

                    if brand_data:
                        growth_df = pd.DataFrame(brand_data)
                        st.dataframe(growth_df, use_container_width=True, hide_index=True)
                    else:
                        st.info("No brand growth data available")
                else:
                    st.info("No brand data available")
            else:
                st.warning("Database connection not available")
        except Exception as e:
            st.error(f"Error loading brand growth data: {e}")

with tab3:
    st.markdown("## Data Management")

    st.markdown("### Add Test Data")

    col1, col2 = st.columns(2)
    with col1:
        test_brand = st.selectbox(
            "Newsletter Brand",
            ["American Conservative AM", "American Conservative PM",
             "Conservatives Daily AM", "Conservatives Daily PM",
             "Worldly Reports AM", "Worldly Reports PM",
             "Americans Daily Digest"],
            key="test_brand"
        )
    with col2:
        test_date = st.date_input("Date", datetime.now(), key="test_date")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        test_sends = st.number_input("Sends", min_value=0, max_value=100000, value=50000, step=1000)
    with col2:
        test_open_rate = st.number_input("Open Rate %", min_value=0.0, max_value=100.0, value=35.0, step=0.5)
    with col3:
        test_ctr = st.number_input("CTR %", min_value=0.0, max_value=20.0, value=4.5, step=0.1)
    with col4:
        test_unsubs = st.number_input("Unsubscribes", min_value=0, max_value=1000, value=50, step=10)

    if st.button("Add Test Data", type="primary", use_container_width=True):
        db = SupabaseDatabase()

        platform = 'beehiiv' if 'Americans Daily Digest' in test_brand else 'tinyemail'
        campaign_type = None
        if 'AM' in test_brand:
            campaign_type = 'AM'
        elif 'PM' in test_brand:
            campaign_type = 'PM'

        opens = int(test_sends * (test_open_rate / 100))
        clicks = int(test_sends * (test_ctr / 100))

        db.add_newsletter_metrics(
            platform=platform,
            date=test_date.strftime('%Y-%m-%d'),
            brand=test_brand,
            campaign_type=campaign_type,
            metrics={
                'sends': test_sends,
                'opens': opens,
                'open_rate': test_open_rate,
                'clicks': clicks,
                'ctr': test_ctr,
                'unsubscribes': test_unsubs,
                'delivered': 98.5,
                'unique_opens': int(opens * 0.85),
                'unique_open_rate': test_open_rate * 0.85,
                'unique_clicks': int(clicks * 0.9),
                'uctr': test_ctr * 0.9,
                'spam': int(test_sends * 0.001),
                'list_size': test_sends,
                'list_growth': int(test_sends * 0.01),
                'unsubscribe_rate': test_unsubs / test_sends if test_sends > 0 else 0
            }
        )

        st.success("Test data added successfully!")
        st.balloons()
        time.sleep(1)
        st.rerun()

    st.markdown("---")
    st.markdown("### Import Historical Data")

    st.info("""
    **Import Sept/Oct Data:**
    Upload your September and October newsletter data CSV files to populate the database.

    **CSV Format Required:**
    - Date, Brand, Sends, Delivered, Opens, Open Rate, Unique Opens, Unique Open Rate,
      Clicks, CTR, Unique Clicks, UCTR, Brand List Size, List Growth, % Unsubscribe, Unsubscribes, Spam
    """)

    uploaded_file = st.file_uploader("Upload CSV", type=['csv'], key="import_csv")

    if uploaded_file is not None:
        try:
            import_df = pd.read_csv(uploaded_file)

            st.write("**Preview:**")
            st.dataframe(import_df.head(10))

            if st.button("Confirm Import", type="primary"):
                db = SupabaseDatabase()

                for _, row in import_df.iterrows():
                    platform = 'beehiiv' if 'Americans Daily Digest' in row['Brand'] else 'tinyemail'
                    campaign_type = None
                    if 'AM' in row['Brand']:
                        campaign_type = 'AM'
                    elif 'PM' in row['Brand']:
                        campaign_type = 'PM'

                    db.add_newsletter_metrics(
                        platform=platform,
                        date=row['Date'],
                        brand=row['Brand'],
                        campaign_type=campaign_type,
                        metrics={
                            'sends': row.get('Sends', 0),
                            'delivered': row.get('Delivered', 0),
                            'opens': row.get('Opens', 0),
                            'open_rate': row.get('Open Rate', 0),
                            'unique_opens': row.get('Unique Opens', 0),
                            'unique_open_rate': row.get('Unique Open Rate', 0),
                            'clicks': row.get('Clicks', 0),
                            'ctr': row.get('CTR', 0),
                            'unique_clicks': row.get('Unique Clicks', 0),
                            'uctr': row.get('UCTR', 0),
                            'list_size': row.get('Brand List Size', 0),
                            'list_growth': row.get('List Growth', 0),
                            'unsubscribes': row.get('Unsubscribes', 0),
                            'unsubscribe_rate': row.get('% Unsubscribe', 0),
                            'spam': row.get('Spam', 0)
                        }
                    )

                st.success(f"Imported {len(import_df)} records successfully!")
                st.balloons()

        except Exception as e:
            st.error(f"Import failed: {str(e)}")
