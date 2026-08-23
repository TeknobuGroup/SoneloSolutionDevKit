@echo off
setlocal
cd /d "%~dp0"
where python >nul 2>nul || (echo Python was not found on PATH. Install Python 3 from python.org and tick "Add to PATH". & pause & exit /b 1)
echo Installing the Sonelo Solution DevKit (kit, worklog, pipeline, CLIs, logins)...
echo If claude-pipeline-starter*.zip is in this folder or in Downloads it is picked up automatically.
echo.
python repo_setup.py install
echo.
echo Done. Open Claude Code in any repo and run /repo-setup, or /new-repo for a new project.
pause
