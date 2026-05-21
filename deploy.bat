@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================
echo   Deploy to GitHub
echo ========================================
echo.

echo Adding changed files...
git add .

git restore --staged DEPLOY_GUIDE.md 2>nul
git restore --staged CONFIG_GUIDE.txt 2>nul

echo.
echo Committing changes...

for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value') do set datetime=%%I

set commit_date=%datetime:~6,2%.%datetime:~4,2%.%datetime:~0,4%
set commit_time=%datetime:~8,2%:%datetime:~10,2%

git commit -m "Auto-deploy: %commit_date% %commit_time%"

if %errorlevel% neq 0 (
    echo.
    echo No changes to commit.
    pause
    exit /b
)

echo.
echo Pushing to GitHub...

git push origin main

if %errorlevel% equ 0 (
    echo.
    echo ========================================
    echo   Deploy complete!
    echo ========================================
) else (
    echo.
    echo ========================================
    echo   Push failed.
    echo ========================================
)

echo.
pause