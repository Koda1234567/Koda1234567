# Звонко на своём Windows-компьютере (без VPS)

**Цель:** первый реальный внутренний звонок из Новофона на отдельного AI-сотрудника, используя ваш Windows ПК как сервер. Это НЕ веб-чат.

> Важное ограничение: Asterisk в WSL2 работает за виртуальной сетью Windows. SIP-регистрация может пройти, а входящий звук или вызов могут не дойти из-за UDP/NAT/файрвола. Это **путь для диагностики**, а не подтверждённый полностью работоспособный вариант. Windows 11 22H2+ поддерживает mirrored networking. Windows 10 потребует альтернативную маршрутизацию либо Linux.

## 1. Подготовка Windows

Откройте PowerShell, исполните **без передачи вывода с личными данными**:

```powershell
Get-ComputerInfo | Select-Object WindowsProductName, WindowsVersion, OsBuildNumber
(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB
wsl --status
wsl --list --verbose
```

На актуальном Windows 11 с WSL2 в PowerShell от администратора:

```powershell
wsl --install -d Ubuntu-24.04
```

Перезагрузка может потребоваться. Запустите Ubuntu из меню «Пуск», создайте Linux-пользователя и пароль **локально**.

Если Windows 11 22H2+, можно опционально включить зеркальный сетевой режим WSL2 (для SIP/RTP он предпочтительнее стандартного NAT):

Файл `%UserProfile%\.wslconfig`:

```ini
[wsl2]
networkingMode=mirrored
firewall=true
```

Применить в PowerShell: `wsl --shutdown`, снова открыть Ubuntu. **Не отключайте файрвол Windows**; для трафика SIP/RTP может понадобиться точечное правило и настройка роутера. Этот режим не гарантирует входящие вызовы, особенно за CGNAT.

Справка Microsoft: https://learn.microsoft.com/windows/wsl/networking

## 2. Подготовка Asterisk на WSL

В терминале Ubuntu:

```bash
sudo apt update
sudo apt install -y git asterisk python3-venv python3-pip curl ffmpeg libsndfile1
git clone https://github.com/Koda1234567/Koda1234567.git
cd Koda1234567/zvonko/telephony
bash -n install-ubuntu.sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
sudo asterisk -rx 'core show version'
```

**Не запускайте** `install-ubuntu.sh` в WSL — он рассчитан на чистый VPS и может конфликтовать с уже установленным Asterisk. На WSL устанавливаем вручную и контролируем каждый шаг.

## 3. Сохранить существующую телефонную линию

- Ваш активный софтфон Новофона и внутренний номер **100** остаются без изменений.
- В Новофоне добавить отдельного сотрудника **101** и собственный SIP-логин для AI. Если бесплатный тариф не даёт второго сотрудника, ничего не покупайте, сначала сообщите об этом.
- SIP-пароль вводится **только в локальной Ubuntu**, не в чат и не в публичный GitHub.
- `asterisk/pjsip.conf.example` показывает синтаксис для регистрации. Создавайте реальный конфиг только после проверки маршрутизации и NAT.

## 4. Голосовые модели, минимум для первого теста

CPU-only ПК с 8 ГБ RAM не потянет большие модели с приемлемой скоростью. Начните с:
- Ollama `qwen2.5:1.5b` (маленькая LLM) — установить по https://ollama.com/download/linux
- STT `WHISPER_MODEL=tiny` (быстрее, хуже точность)
- Vosk TTS `vosk-model-tts-ru-0.9-multi` (5 русских голосов, пакеты/модель скачать с официального проекта https://github.com/alphacep/vosk-tts)

Затем выставить соответствующие параметры в секретном локальном `.env`, не коммитить.

Для правильного real-time ASR/TTS нужен локальный аудиотест и CPU RAM benchmarking, затем Asterisk media bridge. Код в `server.py` может требовать дальнейшей отладки реального звонка.

## 5. Что именно будет считаться успехом

1. Asterisk запущен в WSL, RTP/UDP исправно работает.
2. Отдельная SIP-линия AI зарегистрирована у Новофона (`pjsip show registrations` показывает Registered).
3. Из софтфона на **100** вручную набран **101**.
4. AI отвечает голосом, распознаёт короткую фразу и продолжает разговор; задержки измерены.

**На текущий момент пункты 1–4 не подтверждены на вашем ПК.** Первым делом нужен реальный вывод `wsl --status` и доступная RAM. До этого не советуем менять Windows-сетевые правила и SIP-пароли.

## Быстрая проверка только Windows

В PowerShell:

```powershell
wsl --status
wsl --list --verbose
```

Пришлите только текст вывода этих двух команд и объём памяти, без приватных ключей. После этого подберём один следующий шаг под реальную конфигурацию.
