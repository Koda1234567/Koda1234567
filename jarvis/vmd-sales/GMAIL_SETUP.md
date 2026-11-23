# Подключение Gmail к автономному JARVIS VMD

Состояние на 23.11.2026: **Gmail ChatGPT подключён, но к отдельному Cloudflare Worker не подключён**. Токены Gmail внутри ChatGPT нельзя экспортировать или переиспользовать на внешнем сервере.

## Что уже работает

- Cloudflare Worker `jarvis-vmd-sales` и приватная D1 `jarvis_vmd_sales`.
- Публичный статус без доступа к контактам: https://jarvis-vmd-sales.mishkafedotov09.workers.dev/health
- Генерация персонального письма и отправка Gmail API встроены в `worker.js`, но **не активны без секретов**.

## Действия владельца для Gmail API (один раз)

1. В [Google Cloud Console](https://console.cloud.google.com/apis/credentials) выберите отдельный проект для JARVIS VMD и включите **Gmail API** в разделе APIs & Services → Library.
2. В **Google Auth Platform / OAuth consent screen** укажите собственный Gmail в списке test users, если приложение в режиме Testing. Название приложения — JARVIS VMD. Не добавляйте сторонних пользователей. Обратите внимание: refresh-токены для тестового приложения с Gmail scopes могут истекать через 7 дней, что не подходит для полноценного режима 24/7. Долговечность требует корректной публикации приложения с учётом правил Google.
3. Создайте OAuth client типа **Web application**, в Authorized redirect URIs впишите `https://developers.google.com/oauthplayground`. Сохраните **Client ID** и **Client Secret**.
4. Откройте [OAuth 2.0 Playground](https://developers.google.com/oauthplayground/). В шестерёнке включите **Use your own OAuth credentials**, укажите полученные Client ID и Client Secret. В первом шаге выберите scopes `https://www.googleapis.com/auth/gmail.send` и `https://www.googleapis.com/auth/gmail.readonly`, затем авторизуйте **свой** Gmail. На втором шаге обменяйте code на токены и скопируйте **refresh token**.
5. В [Cloudflare dashboard](https://dash.cloudflare.com/) откройте **Workers & Pages → jarvis-vmd-sales → Settings → Variables and Secrets**. Добавьте как зашифрованные секреты **три** значения: `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN`. Везде выбирайте формат Secret, а не Plaintext.
6. Заново откройте страницу статуса `/health` — поле `gmailConnected` должно стать `true`. Это означает наличие переменных, **не** гарантирует исправность OAuth. После этого необходим тестовый запрос OAuth и контрольная отправка самому себе через квалифицированную запись.
7. Проверяйте письма в **Sent** и ответы в **Inbox**, а события `QUOTE_SENT`, `REPLIED`, `SEND_REVIEW` и ошибки — в закрытой D1 CRM.

**Никогда не отправляйте OAuth client secret и refresh token в чат, Google Документы, публичный GitHub или обычное письмо.** Подключённая Gmail-почта `mishkafedotov09@gmail.com` не обязана быть доступна для внешнего Worker без этой отдельной авторизации.

## Ограничения

- Обычная коммерческая реклама по email без согласия получателя может нарушать законодательство РФ; использовать только разрешённые каналы ответа на запрос закупки/предложения.
- Авторизация не предоставляет права подавать заявки вместо владельца на коммерческих и государственных площадках.
- В CRM допускается только отмеченный проверенным адрес отдела закупок + ссылка на его публикацию и подходящая модель. Из карточки поискового API однозначного адреса покупателя нет.
- Код ограничивает отправку до 12 сообщений за сутки и двух за 5-минутный цикл, исключает автоматическую повторную отправку письма с неопределённым результатом.
