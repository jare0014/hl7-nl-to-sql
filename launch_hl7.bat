@echo off
title HL7 Clinical Data Lake Query Portal
echo ==================================================
echo   Engaging HL7 Clinical Data Lake Server...
echo ==================================================
if not exist .venv (
    echo Python Virtual Environment (.venv) not found.
    echo Running setup.py first...
    python setup.py
)
.venv\Scripts\python.exe hl7_visualizer.py
pause
