// Простой скрипт для отображения сообщения при нажатии на кнопку
<script src="/script.js"></script>
document.addEventListener('DOMContentLoaded', function() {
    const button = document.querySelector('.button');
    
    if (button) {
        button.addEventListener('click', function() {
            alert('Button clicked!');
        });
    }
});
