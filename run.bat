@echo off
title RankVibe Otomasyon Sistemi
cls

echo ============================================
echo      RANKVIBE VIDEO PARÇALAYICI v2.0
echo ============================================

:: Sanal ortam kontrolü ve aktivasyon
if not exist venv (
    echo [!] Sanal ortam bulunamadı! Lütfen önce venv oluşturun.
    pause
    exit
)

call venv\Scripts\activate

:: Kodun çalışması
echo [!] Sunucu baslatiliyor... Lutfen tarayicidan http://localhost:5000 adresine gidin.
python app.py

echo.
echo ============================================
echo         Sunucu kapatildi.
echo ============================================
pause