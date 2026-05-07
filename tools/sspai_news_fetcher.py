#!/usr/bin/env python3
#!/usr/bin/env python3

import requests
from bs4 import BeautifulSoup
import json
import re
from urllib.parse import urljoin

def sspai_fetcher(url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Referer': 'https://sspai.com/',
        'DNT': '1', 
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Insecure-Requests': '1'
    }
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status() 
    except requests.exceptions.RequestException as e:
        return json.dumps({"error": f"Failed to retrieve URL {url}: {e}"})

    soup = BeautifulSoup(response.text, 'html.parser')
    news_items = []
    
    articles = soup.find_all('li', class_='feed-item') 
    
    if not articles:
        articles = soup.find_all('article', class_=re.compile(r'post-card|article-item'))
    
    if not articles: 
        containers = soup.find_all('div', class_=re.compile(r'card|item|list-item'))
        for container in containers:
            title_tag = container.find(['h1', 'h2', 'h3', 'a'], class_=re.compile(r'title|heading|text-h'))
            link_tag = container.find('a', href=True)
            
            if title_tag and link_tag:
                title = title_tag.get_text(strip=True)
                link = link_tag['href']
                if link.startswith('/'):
                    link = urljoin(url, link)
                if title and link and not link.startswith('javascript:'):
                    news_items.append({"title": title, "link": link})
        return json.dumps({"news": news_items[:5]})


    for article in articles:
        title_element = article.find('h3', class_='card-content-title') 
        link_element = article.find('a', href=True) 
        
        title = ""
        link = ""

        if title_element:
            title = title_element.get_text(strip=True)
        elif link_element: 
            title = link_element.get_text(strip=True)

        if link_element and 'href' in link_element.attrs:
            link = link_element['href']
            if link.startswith('/'): 
                link = urljoin(url, link)
        
        title = re.sub(r'\s+', ' ', title).strip()

        if title and link and not link.startswith('javascript:'): 
            news_items.append({"title": title, "link": link})
    
    return json.dumps({"news": news_items[:5]})

import sys
if __name__ == '__main__':
    args_str = sys.argv[1] if len(sys.argv) > 1 else '{}'
    args = json.loads(args_str)
    url = args.get('url')
    if not url:
        print(json.dumps({"error": "URL parameter is missing."}))
    else:
        print(sspai_fetcher(url))