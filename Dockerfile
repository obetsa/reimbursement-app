# Використовуємо легкий nginx для роздачі статичних файлів
FROM nginx:alpine

# Копіюємо наш index.html в nginx
COPY index.html /usr/share/nginx/html/index.html

# Відкриваємо порт 80
EXPOSE 80

# nginx запускається автоматично
