@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Localizador de Ficheiros Duplicados - compilacao autonoma
set "PYEXE="
where py >nul 2>nul && set "PYEXE=py"
if not defined PYEXE (
  for %%P in ("%LocalAppData%\Programs\Python\Python313\python.exe" "%LocalAppData%\Programs\Python\Python312\python.exe" "%LocalAppData%\Programs\Python\Python311\python.exe" "%ProgramFiles%\Python313\python.exe" "%ProgramFiles%\Python312\python.exe") do if not defined PYEXE if exist %%~P set "PYEXE=%%~P"
)
if not defined PYEXE (
  echo ERRO: nao encontrei Python neste computador de compilacao.
  echo O Python so e necessario para COMPILAR; o programa final nao precisa dele.
  echo Como pretende evitar instalacoes adicionais, nao vou instalar Python automaticamente.
  echo Execute este ficheiro num Windows onde Python ja esteja instalado.
  pause
  exit /b 1
)
echo.
echo Python de compilacao: %PYEXE%
echo O EXE final sera preparado com as bibliotecas de que precisa.
echo No computador de destino nao sera necessario instalar Python.
echo.
"%PYEXE%" -m pip install --upgrade pip
if errorlevel 1 goto erro
"%PYEXE%" -m pip install -r requirements-build.txt
if errorlevel 1 goto erro
"%PYEXE%" -m PyInstaller --noconfirm --clean --windowed --onedir --name Localizador_Ficheiros_Duplicados --collect-all PIL --collect-all send2trash --hidden-import PIL.ImageTk --icon=localizador_clf.ico --add-data "localizador_clf.ico;." localizador_duplicados.py
if errorlevel 1 goto erro
if not exist "dist\Localizador_Ficheiros_Duplicados\Localizador_Ficheiros_Duplicados.exe" goto semexe
echo.
echo COMPILACAO CONCLUIDA.
echo EXE: dist\Localizador_Ficheiros_Duplicados\Localizador_Ficheiros_Duplicados.exe
echo Copie a pasta completa dist\Localizador_Ficheiros_Duplicados para usar noutro computador.
echo Nao copie apenas o EXE: os ficheiros de suporte devem acompanhar a aplicacao.
pause
exit /b 0
:semexe
echo ERRO: o PyInstaller terminou mas o EXE esperado nao foi encontrado.
pause
exit /b 1
:erro
echo.
echo A compilacao falhou. Guarde uma captura desta janela para diagnostico.
pause
exit /b 1
