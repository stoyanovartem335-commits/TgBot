@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================
echo   Deploy to GitHub
echo ========================================
echo.

echo Pulling latest changes...
git pull --no-edit
echo.

echo Adding changed files...
git add -A
git reset HEAD DEPLOY_GUIDE.md CONFIG_GUIDE.txt 2>nul

echo.
echo Committing changes...
git diff --cached --quiet
if %errorlevel% equ 0 (
    echo No changes to commit.
    echo.
    pause
    exit /b 0
)

git commit -m "Auto-deploy: %date% %time:~0,8%"

echo.
echo Pushing to GitHub...
git push

if %errorlevel% equ 0 (
    echo.
    echo ========================================
    echo   Deploy complete!
    echo ========================================
) else (
    echo.
    echo ========================================
    echo   Push failed. Check errors above.
    echo ========================================
)

echo.
pause
