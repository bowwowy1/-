@echo off
REM 여행 블로그 초안 생성기 실행 스크립트 (Windows)
REM 이 파일이 있는 폴더로 이동해서 streamlit 실행.

cd /d "%~dp0"

REM streamlit 명령이 PATH 에 있으면 그걸 쓰고,
REM 없으면 python -m streamlit 로 폴백.
where streamlit >nul 2>nul
if %ERRORLEVEL%==0 (
    streamlit run app.py
) else (
    python -m streamlit run app.py
)

REM 오류로 창이 즉시 닫히지 않게 대기
pause
