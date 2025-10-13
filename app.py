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
            "target_audience": "Conservative Americans"
        },
        "americans_digest": {
            "name": "The American's Digest",
            "wp_url": "https://theamericansdigest.com",
            "username": st.secrets.get("ad_username", ""),
            "password": st.secrets.get("ad_password", ""),
            "writer_style": "Walter Cronkite",
            "style_description": "Authoritative, measured, and trustworthy delivery",
            "themes": ["national", "politics", "economy", "culture", "conservative", "breaking"],
            "target_audience": "Mainstream conservatives"
        },
        "conservatives_daily": {
            "name": "Conservatives Daily",
            "wp_url": "https://conservativesdaily.com",
            "username": st.secrets.get("cd_username", ""),
            "password": st.secrets.get("cd_password", ""),
            "writer_style": "Dan Rather",
            "style_description": "Folksy yet authoritative, with investigative edge",
            "themes": ["breaking", "daily", "conservative", "america", "trending"],
            "target_audience": "Daily conservative readers"
        },
        "world_reports": {
            "name": "World Reports",
            "wp_url": "https://worldlyreports.com",
            "username": st.secrets.get("wr_username", ""),
            "password": st.secrets.get("wr_password", ""),
            "writer_style": "Walter Cronkite",
            "style_description": "Global perspective with American viewpoint",
            "themes": ["world", "international", "global", "foreign", "breaking"],
            "target_audience": "Internationally-aware conservatives"
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
    
    MIN_WORDS = 400
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
            st.warning("⚠️ Supabase not configured. Duplicate detection disabled.")
    
    def is_duplicate(self, url: str, content: str, site: str) -> bool:
        """Check if article is duplicate by URL or similar content"""
        if not self.client:
            return False
        
        try:
            url_hash = hashlib.md5(url.encode()).hexdigest()
            content_hash = hashlib.md5(content[:1000].encode()).hexdigest()
            
            # Check if URL was already processed (prevents same article across sites)
            url_check = self.client.table('processed_articles').select('id').eq('url_hash', url_hash).execute()
            if url_check.data:
                return True
            
            # Check if similar content exists (prevents day-over-day duplicates)
            content_check = self.client.table('processed_articles').select('id').eq('content_hash', content_hash).eq('site', site).execute()
            if content_check.data:
                return True
            
            return False
        except Exception as e:
            st.warning(f"Duplicate check error: {str(e)}")
            return False
    
    def add_processed(self, url: str, content: str, title: str, site: str):
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
                'site': site
            }).execute()
        except Exception as e:
            # Ignore duplicate errors
            pass

# ============= NEWS FETCHER =============
class NewsFetcher:
    def fetch_articles(self, themes: List[str]) -> List[Dict]:
        all_articles = []
        categories = self._get_categories(themes)
        
        for category in categories:
            for source in ClickMovementConfig.NEWS_SOURCES.get(category, []):
                try:
                    feed = feedparser.parse(source['rss'])
                    for entry in feed.entries[:15]:
                        all_articles.append({
                            'title': entry.get('title', ''),
                            'link': entry.get('link', ''),
                            'summary': entry.get('summary', ''),
                            'source': source['name'],
                            'score': self._score(entry, themes, source['weight'])
                        })
                except:
                    continue
        
        all_articles.sort(key=lambda x: x['score'], reverse=True)
        return all_articles[:50]
    
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
            r'©\s*\d{4}.*',
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
                model="claude-3-5-sonnet-20241022",
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
            
            for img in soup.select('article img, .article-body img, .entry-content img')[:8]:
                src = img.get('data-src') or img.get('src')
                if src and self._is_valid_image(src):
                    images.append(urljoin(url, src))
            
            seen = set()
            unique_images = []
            for img in images:
                if img not in seen:
                    seen.add(img)
                    unique_images.append(img)
            
            return unique_images[:5]
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
        """Resize image to 860x475 pixels"""
        try:
            response = requests.get(image_url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
            if response.status_code != 200:
                return None
            
            img = Image.open(BytesIO(response.content))
            
            # Convert to RGB if necessary
            if img.mode in ('RGBA', 'LA', 'P'):
                img = img.convert('RGB')
            
            # Target dimensions
            target_width = 860
            target_height = 475
            
            # Calculate aspect ratios
            img_aspect = img.width / img.height
            target_aspect = target_width / target_height
            
            if img_aspect > target_aspect:
                # Image is wider - fit to height, crop width
                new_height = target_height
                new_width = int(target_height * img_aspect)
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                # Crop from center
                left = (new_width - target_width) // 2
                img = img.crop((left, 0, left + target_width, target_height))
            else:
                # Image is taller - fit to width, crop height
                new_width = target_width
                new_height = int(target_width / img_aspect)
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                # Crop from center
                top = (new_height - target_height) // 2
                img = img.crop((0, top, target_width, top + target_height))
            
            # Save to BytesIO
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
        """Get or create a session for this site"""
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
        """Test if WordPress REST API is accessible"""
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
        """Get recent posts from last 7 days for internal linking"""
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
        """Add one internal link at the end of the article"""
        recent_posts = self.get_recent_posts(site_config, limit=5)
        
        if not recent_posts:
            return content
        
        # Pick a random recent post
        import random
        post = random.choice(recent_posts)
        
        # Add link at the end
        internal_link = f'\n\n<p><strong>Related:</strong> <a href="{post["link"]}">{post["title"]}</a></p>'
        return content + internal_link
    
    def publish(self, site_config: Dict, title: str, content: str, status: str = 'draft', 
                image_url: Optional[str] = None, tags: Optional[List[str]] = None) -> Dict:
        try:
            session = self._get_session(site_config)
            api_url = f"{site_config['wp_url']}/wp-json/wp/v2/posts"
            
            # Add internal link
            content_with_link = self.add_internal_link(content, site_config)
            
            # Clean content - remove duplicate H1 tags
            content_cleaned = re.sub(r'<h1>.*?</h1>', '', content_with_link, flags=re.IGNORECASE)
            
            # Ensure proper paragraph formatting
            if '<p>' not in content_cleaned:
                paragraphs = [p.strip() for p in content_cleaned.split('\n\n') if p.strip()]
                content_cleaned = ''.join(f'<p>{p}</p>' for p in paragraphs)
            
            # Remove empty paragraphs
            content_cleaned = re.sub(r'<p>\s*</p>', '', content_cleaned)
            
            payload = {
                'title': title,
                'content': content_cleaned,
                'status': status
            }
            
            # Handle featured image
            featured_media_id = None
            if image_url:
                featured_media_id = self._upload_image(site_config, image_url, title)
                if featured_media_id:
                    payload['featured_media'] = featured_media_id
            
            # Handle tags
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
        """Upload resized image to WordPress media library and return media ID"""
        try:
            session = self._get_session(site_config)
            
            # Resize image
            image_fetcher = ImageFetcher()
            resized_image = image_fetcher.resize_image(image_url)
            
            if not resized_image:
                return None
            
            # Upload to WordPress
            media_url = f"{site_config['wp_url']}/wp-json/wp/v2/media"
            
            files = {
                'file': ('featured-image.jpg', resized_image, 'image/jpeg')
            }
            
            # Remove Content-Type header for multipart upload
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
        """Get or create WordPress tags and return their IDs"""
        try:
            session = self._get_session(site_config)
            tags_url = f"{site_config['wp_url']}/wp-json/wp/v2/tags"
            tag_ids = []
            
            for tag_name in tag_names[:5]:
                # Try to find existing tag
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
                
                # Create new tag if not found
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
        """Generate relevant tags for the article"""
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
    
    def process_site(self, site_key: str, site_config: Dict) -> List[Dict]:
        processed = []
        
        articles = self.fetcher.fetch_articles(site_config['themes'])
        
        for article in articles:
            if len(processed) >= ClickMovementConfig.ARTICLES_PER_SITE:
                break
            
            # Skip if URL already used in this batch
            if article['link'] in self.used_urls:
                continue
            
            # Scrape content first to check for duplicates
            full_content = self.processor.scrape_article(article['link'])
            if not full_content or len(full_content.split()) < 200:
                continue
            
            # Check Supabase for duplicates (by URL and content similarity)
            if self.db.is_duplicate(article['link'], full_content, site_key):
                continue
            
            # Rewrite
            rewritten, headlines = self.processor.rewrite_article(full_content, site_config)
            if not rewritten or len(rewritten.split()) < ClickMovementConfig.MIN_WORDS:
                continue
            
            # Fetch images
            image_urls = self.images.fetch_images(article['link'])
            
            # Generate tags
            tags = self._generate_tags(article['title'], rewritten, site_config)
            
            processed.append({
                'original_title': article['title'],
                'headlines': headlines if headlines else [article['title']],
                'selected_headline': headlines[0] if headlines else article['title'],
                'content': rewritten,
                'source': article['source'],
                'url': article['link'],
                'images': image_urls,
                'selected_image': image_urls[0] if image_urls else None,
                'word_count': len(rewritten.split()),
                'site_config': site_config,
                'tags': tags
            })
            
            # Mark URL as used and add to Supabase
            self.used_urls.add(article['link'])
            self.db.add_processed(article['link'], rewritten, article['title'], site_key)
        
        return processed

# ============= STREAMLIT UI =============
st.set_page_config(page_title="News Intelligence Dashboard", layout="wide")

if 'processed_articles' not in st.session_state:
    st.session_state.processed_articles = {}
if 'published' not in st.session_state:
    st.session_state.published = set()

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
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="header"><h1>News Intelligence Dashboard</h1></div>', unsafe_allow_html=True)

with st.expander("🔧 Troubleshooting WordPress 403 Errors"):
    st.markdown("""
    **If you get 403 Forbidden errors when publishing:**
    
    1. **Enable Application Passwords** (Required for REST API):
       - Go to WordPress Admin → Users → Your Profile
       - Scroll to "Application Passwords" section
       - Create new password with name "NewsIntelligence"
       - Copy the generated password (spaces included)
       - Update the password in your secrets
    
    2. **Check REST API Access**:
       - Visit: `https://yoursite.com/wp-json/wp/v2/posts`
       - Should show JSON data, not a 403 error
    
    3. **Disable Security Plugin Blocking** (if using Wordfence, iThemes, etc.):
       - Wordfence: Go to Firewall → Manage Rate Limiting → Whitelist REST API
       - iThemes Security: Go to Settings → Allow REST API
       - All In One WP Security: Disable "Completely Block Access To REST API"
    
    4. **Check User Permissions**:
       - Your WordPress user must have "Editor" or "Administrator" role
       - Verify in Users → All Users
    
    5. **Contact Host** if issue persists:
       - Some hosts block REST API at server level
       - Ask them to whitelist: `/wp-json/wp/v2/posts`
    
    Click **"Test Connections"** button below to diagnose the issue.
    """)

# Site Selector
col_selector, col1, col2, col3 = st.columns([1.5, 1.5, 1.5, 1])

with col_selector:
    site_options = ["All Sites"] + [config['name'] for config in ClickMovementConfig.WORDPRESS_SITES.values()]
    selected_site = st.selectbox(
        "Select Site to Process",
        site_options,
        key="site_selector"
    )

with col1:
    if st.button("Fetch & Process Articles", type="primary", use_container_width=True):
        processor = NewsProcessor()
        results = {}
        
        # Determine which sites to process
        if selected_site == "All Sites":
            sites_to_process = list(ClickMovementConfig.WORDPRESS_SITES.items())
        else:
            # Find the matching site key
            site_key = [k for k, v in ClickMovementConfig.WORDPRESS_SITES.items() if v['name'] == selected_site][0]
            sites_to_process = [(site_key, ClickMovementConfig.WORDPRESS_SITES[site_key])]
        
        progress = st.progress(0)
        
        for idx, (site_key, site_config) in enumerate(sites_to_process):
            with st.spinner(f"Processing {site_config['name']}..."):
                processed = processor.process_site(site_key, site_config)
                results[site_key] = processed
                st.info(f"✓ {site_config['name']}: Found {len(processed)} articles")
                progress.progress((idx + 1) / len(sites_to_process))
        
        st.session_state.processed_articles = results
        total = sum(len(articles) for articles in results.values())
        st.success(f"Processed {total} articles!")
        st.rerun()

with col2:
    if st.button("Test Connections", use_container_width=True):
        publisher = WordPressPublisher()
        for site_key, site_config in ClickMovementConfig.WORDPRESS_SITES.items():
            result = publisher.test_connection(site_config)
            if result['success']:
                st.success(f"✅ {site_config['name']}: {result['message']}")
            else:
                st.error(f"❌ {site_config['name']}: {result['error']}")

with col3:
    if st.button("Clear All", use_container_width=True):
        st.session_state.processed_articles = {}
        st.session_state.published = set()
        st.rerun()

if st.session_state.processed_articles:
    total = sum(len(a) for a in st.session_state.processed_articles.values())
    published = len(st.session_state.published)
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(f'<div class="stat-box"><h2>{total}</h2><p>Total Articles</p></div>', unsafe_allow_html=True)
    with col2:
        st.markdown(f'<div class="stat-box"><h2>{published}</h2><p>Published</p></div>', unsafe_allow_html=True)
    with col3:
        st.markdown(f'<div class="stat-box"><h2>{total-published}</h2><p>Ready</p></div>', unsafe_allow_html=True)

if st.session_state.processed_articles:
    for site_key, articles in st.session_state.processed_articles.items():
        if not articles:
            continue
        
        site_config = ClickMovementConfig.WORDPRESS_SITES[site_key]
        st.markdown(f"### {site_config['name']}")
        
        for idx, article in enumerate(articles):
            article_id = f"{site_key}_{idx}"
            
            with st.container():
                st.markdown('<div class="article-card">', unsafe_allow_html=True)
                
                selected_headline = st.selectbox(
                    "Select Headline",
                    article['headlines'],
                    key=f"headline_{article_id}"
                )
                
                # Image selection
                selected_image = None
                if article['images']:
                    image_options = ["No Featured Image"] + [f"Image {i+1}" for i in range(len(article['images']))]
                    selected_image_idx = st.selectbox(
                        "Select Featured Image",
                        range(len(image_options)),
                        format_func=lambda x: image_options[x],
                        key=f"image_{article_id}",
                        index=1 if article['images'] else 0
                    )
                    if selected_image_idx > 0:
                        selected_image = article['images'][selected_image_idx - 1]
                        st.caption(f"✓ Will use: {image_options[selected_image_idx]} (resized to 860x475px)")
                
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.caption(f"Source: {article['source']}")
                with col2:
                    st.caption(f"Words: {article['word_count']}")
                with col3:
                    if article_id in st.session_state.published:
                        st.caption("Status: PUBLISHED")
                
                if article.get('tags'):
                    st.write("**Tags:**")
                    st.caption(", ".join(article['tags']))
                
                if article['images']:
                    st.write("**Available Images:**")
                    img_cols = st.columns(min(3, len(article['images'])))
                    for img_idx, img_url in enumerate(article['images'][:3]):
                        with img_cols[img_idx]:
                            try:
                                response = requests.get(img_url, timeout=5, headers={'User-Agent': 'Mozilla/5.0'})
                                img = Image.open(BytesIO(response.content))
                                st.image(img, use_container_width=True)
                                if selected_image and img_url == selected_image:
                                    st.caption(f"**Image {img_idx+1}** ⭐ Selected")
                                else:
                                    st.caption(f"Image {img_idx+1}")
                                st.caption(f"[Link]({img_url})")
                            except Exception as e:
                                st.warning(f"⚠️ Image {img_idx+1} failed to load")
                                st.caption(f"[View Image]({img_url})")
                
                with st.expander("Read Article"):
                    st.write(article['content'])
                
                col1, col2, col3, col4 = st.columns(4)
                
                with col1:
                    if st.button("Publish Draft", key=f"draft_{article_id}", 
                               disabled=article_id in st.session_state.published,
                               use_container_width=True):
                        publisher = WordPressPublisher()
                        result = publisher.publish(
                            site_config,
                            selected_headline,
                            article['content'],
                            'draft',
                            image_url=selected_image,
                            tags=article.get('tags', [])
                        )
                        if result['success']:
                            success_msg = f"Draft created! [Edit]({result['edit_url']})"
                            if result.get('featured_image_set'):
                                success_msg += " ✓ Image"
                            if result.get('tags_set', 0) > 0:
                                success_msg += f" ✓ {result['tags_set']} tags"
                            if result.get('internal_link_added'):
                                success_msg += " ✓ Internal link"
                            st.success(success_msg)
                            st.session_state.published.add(article_id)
                            st.rerun()
                        else:
                            st.error(f"Failed: {result['error']}")
                
                with col2:
                    if st.button("Publish Live", key=f"live_{article_id}", 
                               disabled=article_id in st.session_state.published,
                               type="primary",
                               use_container_width=True):
                        publisher = WordPressPublisher()
                        result = publisher.publish(
                            site_config,
                            selected_headline,
                            article['content'],
                            'publish',
                            image_url=selected_image,
                            tags=article.get('tags', [])
                        )
                        if result['success']:
                            success_msg = f"Published! [View]({result['edit_url']})"
                            if result.get('featured_image_set'):
                                success_msg += " ✓ Image"
                            if result.get('tags_set', 0) > 0:
                                success_msg += f" ✓ {result['tags_set']} tags"
                            if result.get('internal_link_added'):
                                success_msg += " ✓ Internal link"
                            st.success(success_msg)
                            st.session_state.published.add(article_id)
                            st.rerun()
                        else:
                            st.error(f"Failed: {result['error']}")
                
                with col3:
                    if st.button("Regenerate Headline", key=f"regen_{article_id}",
                               use_container_width=True):
                        processor = ContentProcessor()
                        _, new_headlines = processor.rewrite_article(
                            article['content'][:1000],
                            site_config
                        )
                        if new_headlines:
                            st.session_state.processed_articles[site_key][idx]['headlines'] = new_headlines
                            st.rerun()
                
                with col4:
                    st.link_button("Source", article['url'], use_container_width=True)
                
                st.markdown('</div>', unsafe_allow_html=True)

else:
    st.info("Click 'Fetch & Process Articles' to begin")
