# -*- coding: utf-8 -*-
import os, re, html, ssl, smtplib, hashlib, logging, time
from pathlib import Path
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit, urlunsplit
import requests, feedparser

# =============================================================================
# 1. 기본 실행 환경 설정
# =============================================================================
KST = timezone(timedelta(hours=9))
NOW = datetime.now(KST)

OUT = Path(os.getenv('OUTPUT_DIR', 'output'))
HOURS = int(os.getenv('LOOKBACK_HOURS', '36'))
LIMIT = int(os.getenv('MAX_PER_FEED', '30'))
SEND = os.getenv('SEND_EMAIL', 'true').lower() in ('1', 'true', 'yes')

# =============================================================================
# 2. 이메일 기본 수신자 설정
# =============================================================================
EMAIL_RECEIVERS = [
    'ohmj@jchyun.com',
    'smoh@jchyun.com',
    'nice@innogrid.com',
    'redsun@innogrid.com',
    'mjjeong@innogrid.com',
    'kdw@innogrid.com',
    'kimjy@innogrid.com',
    'sungjin.lee@innogrid.com',
    'cjbkhh@innogrid.com'
]

log = logging.getLogger('news')
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

# =============================================================================
# 3. 국내 15개 및 해외 20개 RSS 피드 설정
# =============================================================================
FEEDS = OrderedDict([
('전자신문 IT',('국내','https://rss.etnews.com/03.xml')),('전자신문 AI',('국내','https://rss.etnews.com/04046.xml')),
('전자신문 보안',('국내','https://rss.etnews.com/04045.xml')),('전자신문 벤처',('국내','https://rss.etnews.com/22069.xml')),
('보안뉴스',('국내','https://www.boannews.com/custom/news_rss.asp')),('데일리시큐',('국내','https://www.dailysecu.com/rss/allArticle.xml')),
('아이티데일리',('국내','https://www.itdaily.kr/rss/allArticle.xml')),('데이터넷',('국내','https://www.datanet.co.kr/rss/allArticle.xml')),
('디지털데일리',('국내','https://www.ddaily.co.kr/rss/allArticle.xml')),('블로터',('국내','https://www.bloter.net/rss/allArticle.xml')),
('AI타임스',('국내','https://www.aitimes.com/rss/allArticle.xml')),('테크M',('국내','https://www.techm.kr/rss/allArticle.xml')),
('벤처스퀘어',('국내','https://www.venturesquare.net/feed')),
('TechCrunch',('해외','https://techcrunch.com/feed/')),('The Verge',('해외','https://www.theverge.com/rss/index.xml')),
('WIRED',('해외','https://www.wired.com/feed/rss')),('Ars Technica',('해외','https://feeds.arstechnica.com/arstechnica/index')),
('ZDNET',('해외','https://www.zdnet.com/feed/')),('MIT Technology Review',('해외','https://www.technologyreview.com/feed/')),
('VentureBeat',('해외','https://venturebeat.com/feed/')),('Engadget',('해외','https://www.engadget.com/rss.xml')),
('Computerworld',('해외','https://www.computerworld.com/index.rss')),('The Register',('해외','https://www.theregister.com/headlines.atom')),
('Hacker News',('해외','https://news.ycombinator.com/rss')),('BleepingComputer',('해외','https://www.bleepingcomputer.com/feed/')),
('Krebs on Security',('해외','https://krebsonsecurity.com/feed/')),('Dark Reading',('해외','https://www.darkreading.com/rss.xml')),
('Google Cloud Blog',('해외','https://cloudblog.withgoogle.com/rss/')),('AWS News Blog',('해외','https://aws.amazon.com/blogs/aws/feed/')),
('Microsoft Azure Blog',('해외','https://azure.microsoft.com/en-us/blog/feed/')),('NVIDIA Blog',('해외','https://blogs.nvidia.com/feed/')),
('Semiconductor Engineering',('해외','https://semiengineering.com/feed/'))])

# =============================================================================
# 4. 뉴스 카테고리 분류 키워드
# =============================================================================
RULES = OrderedDict([
('AI',['인공지능','생성형 ai','artificial intelligence','machine learning','llm','chatgpt','openai','anthropic','claude','gemini','copilot','deepseek','agentic']),
('보안',['보안','해킹','랜섬웨어','악성코드','취약점','사이버','security','cyber','ransomware','malware','vulnerability','breach','zero-day','phishing']),
('클라우드',['클라우드','데이터센터','가상화','쿠버네티스','cloud','aws','azure','google cloud','kubernetes','docker','serverless','vmware']),
('반도체',['반도체','파운드리','hbm','웨이퍼','semiconductor','chip','nvidia','amd','intel','tsmc','qualcomm','foundry']),
('모바일',['모바일','스마트폰','갤럭시','아이폰','안드로이드','mobile','smartphone','iphone','android','wearable','tablet','ios']),
('스타트업',['스타트업','벤처','투자 유치','시드','startup','venture','funding','fundraise','seed round','series a','unicorn']),
('엔터프라이즈',['기업','엔터프라이즈','cio','디지털 전환','enterprise','business','saas','software','database','platform','policy'])])

# =============================================================================
# 5. 텍스트 정리, 게시일 변환, 분류 및 URL 정규화 함수
# =============================================================================
def clean(x): return re.sub(r'\s+',' ',html.unescape(re.sub(r'<[^>]+>',' ',str(x or '')))).strip()
def dt_of(e):
 for k in ('published_parsed','updated_parsed','created_parsed'):
  v=getattr(e,k,None)
  if v:return datetime(*v[:6],tzinfo=timezone.utc).astimezone(KST)
 for k in ('published','updated','created'):
  try:
   d=parsedate_to_datetime(getattr(e,k,'')); return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(KST)
  except: pass
 return None
def category(text):
 t=text.lower(); score={c:sum(k in t for k in ks) for c,ks in RULES.items()}; w=max(score,key=score.get)
 return w if score[w] else '엔터프라이즈'
def canon(u):
 p=urlsplit(u); return urlunsplit((p.scheme.lower(),p.netloc.lower(),p.path.rstrip('/'),'',''))

# =============================================================================
# 6. RSS 수집, 재시도 및 중복 제거
# =============================================================================
def collect():
    s = requests.Session()
    s.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'application/rss+xml,application/atom+xml,application/xml,text/xml,*/*;q=0.9',
        'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
        'Connection': 'keep-alive'
    })
    
    rows = []
    cutoff = NOW - timedelta(hours=HOURS)
    
    for source, (region, url) in FEEDS.items():
        for attempt in range(2):
            try:
                r = s.get(url, timeout=10) 
                r.raise_for_status()
                f = feedparser.parse(r.content)
                if getattr(f, 'bozo', False) and not f.entries:
                    raise ValueError(getattr(f, 'bozo_exception', 'RSS parse error'))
                n = 0
                for e in f.entries[:LIMIT]:
                    title = clean(getattr(e, 'title', ''))
                    link = canon(getattr(e, 'link', ''))
                    summary = clean(getattr(e, 'summary', getattr(e, 'description', '')))[:500]
                    pub = dt_of(e)
                    if title and link and (not pub or pub >= cutoff):
                        rows.append({
                            'category': category(title + ' ' + summary + ' ' + source),
                            'title': title,
                            'link': link,
                            'source': source,
                            'region': region,
                            'published': pub,
                            'summary': summary
                        })
                        n += 1
                log.info('%s: %d건', source, n)
                break
            except Exception as ex:
                if attempt == 1: 
                    log.warning('%s 실패: %s', source, ex)
                else: 
                    time.sleep(2)
                    
    unique = {}
    for a in rows:
        key = hashlib.sha256(re.sub(r'[^0-9a-z가-힣]+', '', a['title'].lower()).encode()).hexdigest()
        unique.setdefault(key, a)
    return sorted(unique.values(), key=lambda a: a['published'] or datetime.min.replace(tzinfo=KST), reverse=True)

# =============================================================================
# 7. HTML 이메일 본문 생성 (이미지 UI 스타일 적용)
# =============================================================================
def html_report(rows):
    sections = []
    for cat in RULES:
        data = [a for a in rows if a['category'] == cat]
        if not data: continue
        
        items = []
        for a in data:
            summary = a['summary']
            if len(summary) > 130: summary = summary[:130] + '...'
            pub_date = a["published"].strftime("%Y-%m-%d %H:%M") if a["published"] else "날짜 미제공"
            
            card = f'''
            <div style="background-color: #ffffff; border-radius: 8px; padding: 25px; margin-bottom: 20px; box-shadow: 0 2px 6px rgba(0,0,0,0.04);">
                <div style="color: #6d28d9; font-size: 13px; font-weight: bold; margin-bottom: 10px;">
                    {html.escape(a["source"])} <span style="color:#cbd5e1; font-weight:normal; margin:0 5px;">|</span> <span style="color:#94a3b8; font-weight:normal;">{pub_date}</span>
                </div>
                <a href="{html.escape(a["link"], quote=True)}" target="_blank" style="text-decoration: none; color: #111827; font-size: 18px; font-weight: bold; display: block; margin-bottom: 12px; line-height: 1.4; word-break: keep-all;">
                    {html.escape(a["title"])}
                </a>
                <div style="color: #4b5563; font-size: 14px; line-height: 1.6; word-break: keep-all;">
                    {html.escape(summary)}
                </div>
            </div>
            '''
            items.append(card)

        sections.append(f'<h2 style="color: #1e3a8a; margin: 40px 0 20px; font-size: 20px; font-weight: bold;">{cat} <span style="color: #94a3b8; font-size: 16px;">({len(data)})</span></h2>{"".join(items)}')

    html_body = f'''<!doctype html>
    <html>
    <head>
        <meta charset="utf-8">
    </head>
    <body style="font-family: 'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif; background-color: #f7f5fa; margin: 0; padding: 40px 20px;">
        <div style="max-width: 760px; margin: 0 auto;">
            <div style="text-align: center; margin-bottom: 50px; padding-top: 20px;">
                <span style="background-color: #6d28d9; color: #ffffff; padding: 6px 16px; border-radius: 20px; font-size: 13px; font-weight: bold; letter-spacing: 0.5px;">이달의 IT 뉴스</span>
                <h1 style="margin-top: 20px; font-size: 28px; font-weight: bold; color: #111827; letter-spacing: -1px; word-break: keep-all;">AI 시대, 달라지는 인프라 선택 기준</h1>
                <p style="color: #64748b; font-size: 14px; margin-top: 15px;"><b>{NOW:%Y-%m-%d}</b> 기준 최근 {HOURS}시간 기사 리포트</p>
            </div>
            {"".join(sections)}
            <hr style="border: 0; border-top: 1px solid #e2e8f0; margin: 40px 0;">
            <div style="text-align: center; color: #94a3b8; font-size: 12px; margin-bottom: 20px;">
                <p>본 메일의 원문 제목과 링크는 각 매체에 귀속됩니다.</p>
            </div>
        </div>
    </body>
    </html>'''
    return html_body

# =============================================================================
# 8. SMTP 로그인 및 HTML 본문 메일 발송
# =============================================================================
def mail(body):
    if not SEND: 
        log.info('SEND_EMAIL=false: 메일 생략')
        return
        
    sender = os.getenv('EMAIL_SENDER', '').strip()
    password = os.getenv('EMAIL_PASSWORD', '').strip()
    env_receivers = os.getenv('EMAIL_RECV', '').strip()
    receivers = ([x.strip() for x in re.split('[,;]', env_receivers) if x.strip()]
                 if env_receivers else EMAIL_RECEIVERS)
                 
    if not(sender and password and receivers): 
        raise RuntimeError('EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECV가 필요합니다.')
 
    try:
        with smtplib.SMTP(os.getenv('SMTP_HOST','smtp.gmail.com'), int(os.getenv('SMTP_PORT','587')), timeout=30) as s:
            s.ehlo()
            s.starttls(context=ssl.create_default_context())
            s.ehlo()
            s.login(sender, password)
            
            for receiver in receivers:
                msg = MIMEMultipart('alternative')
                msg['Subject'] = f'[Daily IT News] {NOW:%Y-%m-%d} 국내외 IT 뉴스'
                msg['From'] = sender
                msg['To'] = receiver
                
                msg.attach(MIMEText('HTML 뷰어가 지원되는 이메일 클라이언트에서 확인해 주세요.', 'plain', 'utf-8'))
                msg.attach(MIMEText(body, 'html', 'utf-8'))
                
                s.send_message(msg)
                log.info('메일 발송 완료: %s', receiver)
                
    except smtplib.SMTPAuthenticationError:
        log.error('❌ 메일 발송 실패: SMTP 인증 오류. 이메일 계정의 비밀번호가 잘못되었거나 앱 비밀번호 설정이 필요합니다. 구글 계정인 경우 "앱 비밀번호(16자리)"를 발급받아 환경 변수(EMAIL_PASSWORD)에 등록하세요.')
    except Exception as e:
        log.error('❌ 메일 발송 중 알 수 없는 오류 발생: %s', e)

# =============================================================================
# 9. 메인 실행 순서
# =============================================================================
def main():
 OUT.mkdir(parents=True, exist_ok=True); rows = collect()
 if not rows: log.error('수집 기사 없음'); return 2
 
 h = OUT / f'Daily_IT_News_{NOW:%Y%m%d}.html'
 body = html_report(rows)
 h.write_text(body, encoding='utf-8')
 
 mail(body)
 log.info('완료: HTML 메일 렌더링 및 %s 경로 백업', OUT)
 return 0

if __name__=='__main__': raise SystemExit(main())
