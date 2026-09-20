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
    'cjbkhh@innogrid.com',
    'whkwon@nanuminfo.com'   
]

log = logging.getLogger('news')
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

# =============================================================================
# 3. 맞춤형 키워드(Google News) 및 접속 안정성 확보 매체 RSS 피드 설정
# =============================================================================
FEEDS = OrderedDict([
# 구글 뉴스 맞춤형 키워드 검색 (가장 관련성 높은 타겟 기사 수집)
('맞춤뉴스: AI 인프라', ('국내', 'https://news.google.com/rss/search?q=AI+서버+OR+NPU+OR+GPU+OR+HBM&hl=ko&gl=KR&ceid=KR:ko')),
('맞춤뉴스: 클라우드/가상화', ('국내', 'https://news.google.com/rss/search?q=클라우드+이전+OR+데이터센터+OR+가상화+OR+오픈스택&hl=ko&gl=KR&ceid=KR:ko')),
('맞춤뉴스: 공공/엔터프라이즈', ('국내', 'https://news.google.com/rss/search?q=공공+정보시스템+OR+엔터프라이즈+IT+OR+디지털트윈&hl=ko&gl=KR&ceid=KR:ko')),

# 기존 우수 국내 IT 매체
('전자신문 IT',('국내','https://rss.etnews.com/03.xml')),
('전자신문 AI',('국내','https://rss.etnews.com/04046.xml')),
('아이티데일리',('국내','https://www.itdaily.kr/rss/allArticle.xml')),
('데이터넷',('국내','https://www.datanet.co.kr/rss/allArticle.xml')),
('블로터',('국내','https://www.bloter.net/rss/allArticle.xml')),
('AI타임스',('국내','https://www.aitimes.com/rss/allArticle.xml')),
('테크M',('국내','https://www.techm.kr/rss/allArticle.xml')),

# 해외 주요 매체
('TechCrunch',('해외','https://techcrunch.com/feed/')),
('The Verge',('해외','https://www.theverge.com/rss/index.xml')),
('WIRED',('해외','https://www.wired.com/feed/rss')),
('ZDNET',('해외','https://www.zdnet.com/feed/')),
('Computerworld',('해외','https://www.computerworld.com/index.rss')),
('The Register',('해외','https://www.theregister.com/headlines.atom')),
('AWS News Blog',('해외','https://aws.amazon.com/blogs/aws/feed/')),
('NVIDIA Blog',('해외','https://blogs.nvidia.com/feed/')),
('Semiconductor Engineering',('해외','https://semiengineering.com/feed/'))])

# =============================================================================
# 4. 뉴스 카테고리 분류 키워드
# =============================================================================
RULES = OrderedDict([
('AI/인프라',['인공지능','생성형 ai','llm','ai 서버','npu','gpu','데이터센터','hbm','nvidia','amd']),
('클라우드',['클라우드','가상화','쿠버네티스','오픈스택','cloud','aws','azure','kubernetes','vmware']),
('보안',['보안','해킹','랜섬웨어','악성코드','취약점','security','cyber','ransomware','vulnerability']),
('반도체',['반도체','파운드리','웨이퍼','semiconductor','chip','intel','tsmc','qualcomm']),
('엔터프라이즈',['기업','공공','디지털 전환','디지털트윈','정보시스템','enterprise','saas','platform'])])

# =============================================================================
# 5. 텍스트 정리, 게시일 변환, 분류 및 썸네일 추출 함수
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
 p = urlsplit(u)
 return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path, p.query, ''))

def extract_image(e):
    if hasattr(e, 'media_content'):
        for m in e.media_content:
            if m.get('url') and (m.get('medium') == 'image' or 'image' in m.get('type', '')): return m.get('url')
    if hasattr(e, 'links'):
        for l in e.links:
            if l.get('type', '').startswith('image/') and l.get('href'): return l.get('href')
    raw_html = getattr(e, 'summary', '') + getattr(e, 'description', '')
    if hasattr(e, 'content'):
        for c in e.content: raw_html += c.get('value', '')
    match = re.search(r'<img[^>]+src=["\'](http[^"\']+)["\']', raw_html, re.IGNORECASE)
    if match: return match.group(1)
    return ''

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
                    img_url = extract_image(e)
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
                            'summary': summary,
                            'image': img_url
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
# 7. 요약본 생성 (맞춤 기사 최우선 반영 로직 추가)
# =============================================================================
def generate_summary(rows):
    if not rows: return "", "오늘의 주요 IT 이슈"
    
    # 맞춤 키워드로 수집된 기사들을 필터링
    custom_articles = [r for r in rows if '맞춤뉴스' in r['source']]
    
    # 1. 메인 타이틀: 맞춤 뉴스 중 가장 최신 기사를 최우선으로 노출
    top_article = custom_articles[0] if custom_articles else rows[0]
    main_headline = top_article['title']
    if len(main_headline) > 42:
        main_headline = main_headline[:42] + "..."
    main_headline = html.escape(main_headline)
    
    # 2. 브리핑(하이라이트) 5개 추출 로직
    highlights = []
    added_links = set()
    seen_cats = set()
    
    # A. 맞춤 기사 우선 추출 (최대 3개 할당, 가급적 다양한 카테고리로)
    for r in custom_articles:
        if r['category'] not in seen_cats:
            highlights.append(f'<li style="margin-bottom: 8px;"><span style="color:#e11d48; font-weight:bold;">[🎯맞춤픽]</span> <span style="color:#6d28d9; font-weight:bold;">[{r["category"]}]</span> <a href="{html.escape(r["link"], quote=True)}" target="_blank" style="text-decoration: none; color: #334155;">{html.escape(r["title"])}</a></li>')
            seen_cats.add(r['category'])
            added_links.add(r['link'])
        if len(highlights) >= 3:
            break
            
    # B. 나머지 브리핑 자리는 일반 최신 뉴스로 채우기 (카테고리 중복 방지)
    for r in rows:
        if len(highlights) >= 5: break
        if r['link'] not in added_links and r['category'] not in seen_cats:
            highlights.append(f'<li style="margin-bottom: 8px;"><span style="color:#6d28d9; font-weight:bold;">[{r["category"]}]</span> <a href="{html.escape(r["link"], quote=True)}" target="_blank" style="text-decoration: none; color: #334155;">{html.escape(r["title"])}</a></li>')
            seen_cats.add(r['category'])
            added_links.add(r['link'])
            
    # C. 위 조건으로 5개가 다 채워지지 않았다면, 남은 기사 중 최신순으로 단순 추가
    for r in rows:
        if len(highlights) >= 5: break
        if r['link'] not in added_links:
            prefix = '<span style="color:#e11d48; font-weight:bold;">[🎯맞춤픽]</span> ' if '맞춤뉴스' in r['source'] else ''
            highlights.append(f'<li style="margin-bottom: 8px;">{prefix}<span style="color:#6d28d9; font-weight:bold;">[{r["category"]}]</span> <a href="{html.escape(r["link"], quote=True)}" target="_blank" style="text-decoration: none; color: #334155;">{html.escape(r["title"])}</a></li>')
            added_links.add(r['link'])
            
    summary_html = f'''
    <div style="background-color: #f8fafc; border-left: 4px solid #6d28d9; padding: 18px 25px; margin: 25px auto 40px auto; border-radius: 6px; text-align: left; font-size: 14px; color: #334155; line-height: 1.6; max-width: 680px; box-shadow: 0 1px 3px rgba(0,0,0,0.02);">
        <p style="margin: 0 0 12px 0; font-size: 15px;"><b>💡 오늘의 IT 동향 브리핑</b></p>
        <p style="margin: 0 0 12px 0;">최근 {HOURS}시간 동안 총 <b>{len(rows)}건</b>의 기사가 수집되었습니다. 특히 설정하신 <b>관심 키워드(AI 인프라, 클라우드, 디지털 전환 등)</b>를 기반으로 큐레이션 된 최신 맞춤 헤드라인은 다음과 같습니다.</p>
        <ul style="margin: 0; padding-left: 20px; list-style-type: disc;">
            {"".join(highlights)}
        </ul>
    </div>
    '''
    return summary_html, main_headline

# =============================================================================
# 8. HTML 이메일 본문 렌더링 (썸네일 이미지 포함)
# =============================================================================
def html_report(rows):
    summary_section, main_headline = generate_summary(rows)
    
    sections = []
    for cat in RULES:
        data = [a for a in rows if a['category'] == cat]
        if not data: continue
        
        items = []
        for a in data:
            summary = a['summary']
            if len(summary) > 130: summary = summary[:130] + '...'
            pub_date = a["published"].strftime("%Y-%m-%d %H:%M") if a["published"] else "날짜 미제공"
            
            img_tag = f'<div style="margin-bottom: 15px;"><a href="{html.escape(a["link"], quote=True)}" target="_blank"><img src="{a["image"]}" alt="기사 썸네일" style="max-width: 100%; height: auto; border-radius: 6px; object-fit: cover;"></a></div>' if a.get('image') else ''
            
            card = f'''
            <div style="background-color: #ffffff; border-radius: 8px; padding: 25px; margin-bottom: 20px; box-shadow: 0 2px 6px rgba(0,0,0,0.04);">
                <div style="color: #6d28d9; font-size: 13px; font-weight: bold; margin-bottom: 12px;">
                    {html.escape(a["source"])} <span style="color:#cbd5e1; font-weight:normal; margin:0 5px;">|</span> <span style="color:#94a3b8; font-weight:normal;">{pub_date}</span>
                </div>
                {img_tag}
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
            <div style="text-align: center; margin-bottom: 20px; padding-top: 20px;">
                <span style="background-color: #6d28d9; color: #ffffff; padding: 6px 16px; border-radius: 20px; font-size: 13px; font-weight: bold; letter-spacing: 0.5px;">오늘의 IT 뉴스</span>
                <h1 style="margin-top: 20px; font-size: 26px; font-weight: bold; color: #111827; letter-spacing: -1px; word-break: keep-all; line-height: 1.4;">{main_headline}</h1>
                <p style="color: #64748b; font-size: 14px; margin-top: 15px;"><b>{NOW:%Y-%m-%d}</b> 기준 최근 {HOURS}시간 기사 리포트</p>
            </div>
            
            <!-- 10줄 이내 동향 브리핑 -->
            {summary_section}
            
            {"".join(sections)}
            
            <hr style="border: 0; border-top: 1px solid #e2e8f0; margin: 40px 0;">
            <div style="text-align: center; color: #94a3b8; font-size: 12px; margin-bottom: 20px;">
                <p>본 메일의 원문 제목과 링크 및 이미지는 각 매체에 귀속됩니다.</p>
            </div>
        </div>
    </body>
    </html>'''
    return html_body

# =============================================================================
# 9. SMTP 로그인 및 HTML 본문 메일 발송
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
        log.error('❌ 메일 발송 실패: SMTP 인증 오류. 이메일 계정의 비밀번호가 잘못되었거나 앱 비밀번호 설정이 필요합니다.')
    except Exception as e:
        log.error('❌ 메일 발송 중 알 수 없는 오류 발생: %s', e)

# =============================================================================
# 10. 메인 실행 순서
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
