# Daily IT News

1. `daily_it_news.py`, `requirements.txt`를 저장소 루트에 둡니다.
2. `daily-it-news.yml`은 `.github/workflows/daily-it-news.yml`로 옮깁니다.
3. GitHub Actions secrets에 `EMAIL_SENDER`, `EMAIL_PASSWORD`, `EMAIL_RECV`를 등록합니다.
4. Actions 탭의 `workflow_dispatch`로 먼저 수동 테스트합니다.

로컬 무메일 테스트:
```bash
python -m pip install -r requirements.txt
SEND_EMAIL=false python daily_it_news.py
```

`EMAIL_RECV`는 쉼표 또는 세미콜론으로 여러 주소를 구분합니다. Gmail/Workspace는 조직 정책에 맞는 앱 비밀번호 또는 SMTP 인증을 사용하세요. RSS 주소는 매체 정책에 따라 바뀔 수 있으며, 실패한 피드는 경고 후 건너뜁니다. 이 프로젝트의 "전부"는 등록된 35개 RSS가 제공하는 기사 범위입니다.
