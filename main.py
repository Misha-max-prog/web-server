import socket
import threading
import re
import os
from urllib.parse import unquote

class Request:
    def __init__(self, method, path, headers, body):
        self.method = method
        self.path = unquote(path)
        self.headers = headers
        self.body = body

class Response:
    def __init__(self, status_code=200, body='', headers=None):
        self.status_code = status_code
        self.body = body
        self.headers = headers or {'Content-Type': 'text/html'}

    def to_http(self):
        reason = {200: 'OK', 404: 'Not Found', 400: 'Bad Request'}.get(self.status_code, 'OK')
        headers = ''.join(f'{k}: {v}\r\n' for k, v in self.headers.items())
        return f'HTTP/1.1 {self.status_code} {reason}\r\n{headers}\r\n{self.body}'.encode()

class WebServer:
    def __init__(self, host='localhost', port=8080, hostname=None, max_threads=10):
        self.host = host
        self.port = port
        self.hostname = hostname or host
        self.max_threads = max_threads
        self.routes = {'GET': [], 'POST': []}
        self.file_routes = {}
        self.dir_routes = {}
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.running = False
        self.threads = []

    # регистрация обработчиков
    def get(self, path):
        return self._add_route('GET', path)

    def post(self, path):
        return self._add_route('POST', path)

    # добавление маршрутов
    def _add_route(self, method, path):
        def decorator(func):
            self.routes[method].append((re.compile(f'^{path}$'), func))
            return func
        return decorator

    # отдать один файл
    def handle_file(self, path, file_path):
        self.file_routes[path] = file_path

    # листинг папки
    def handle_dir(self, url_path, dir_path):
        self.dir_routes[url_path] = dir_path

    # превращаем HTTP-запрос в объект
    def _parse_request(self, data):
        try:
            lines = data.split('\r\n')
            method, path, _ = lines[0].split()
            headers = {}
            i = 1
            while lines[i]:
                key, value = lines[i].split(': ', 1)
                headers[key] = value
                i += 1
            body = '\r\n'.join(lines[i+1:])
            return Request(method, path, headers, body)
        except:
            return None

    # обработка одного клиента
    def _handle_client(self, client_socket):
        try:
            request_data = client_socket.recv(4096).decode('utf-8')
            print(request_data)
            request = self._parse_request(request_data)
            if not request:
                response = Response(400, 'Bad Request')
                client_socket.sendall(response.to_http())
                client_socket.close()
                return

            response = self._dispatch(request)
            client_socket.sendall(response.to_http())
        finally:
            client_socket.close()

    # находим, кто должен обработать запрос
    def _dispatch(self, request):
        method_routes = self.routes.get(request.method, [])
        for pattern, handler in method_routes:
            if pattern.match(request.path):
                return handler(request)

        if request.method == 'GET':
            if request.path in self.file_routes:
                return self._serve_file(self.file_routes[request.path])
            for route, folder in self.dir_routes.items():
                if request.path.startswith(route):
                    return self._serve_dir(folder, request.path[len(route):])

        return Response(404, 'Not Found')

    # отдаём файл
    def _serve_file(self, path):
        try:
            with open(path, 'r', encoding='utf-8') as f:  # Читаем файл в бинарном режиме
                body = f.read()
                # Определяем тип контента в зависимости от расширения файла
                content_type = self._guess_type(path)
                return Response(200, body, {'Content-Type': content_type})
        except FileNotFoundError:
            return Response(404, 'File not found')

    # отдаём содержимое папки или файл из неё
    def _serve_dir(self, dir_path, sub_path):
        full_path = os.path.join(dir_path, sub_path.lstrip('/'))
        if os.path.isdir(full_path):
            files = os.listdir(full_path)
            body = '<br>'.join(files)
            return Response(200, body)
        elif os.path.isfile(full_path):
            return self._serve_file(full_path)
        else:
            return Response(404, 'Not found')

    # определяем тип файла
    def _guess_type(self, filename):
        if filename.endswith('.html'): return 'text/html; charset=utf-8'
        if filename.endswith('.css'): return 'text/css; charset=utf-8'
        if filename.endswith('.js'): return 'application/javascript; charset=utf-8'
        return 'application/octet-stream'

    # запуск
    def start(self):
        self.server_socket.settimeout(1)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(5)
        self.running = True
        print(f'Serving on http://{self.host}:{self.port}')

        try:
            while self.running:
                try:
                    client_socket, addr = self.server_socket.accept()
                    print(f"Connection accepted from {addr}")
                except socket.timeout:
                    continue
                thread = threading.Thread(target=self._handle_client, args=(client_socket,))
                thread.start()
                self.threads.append(thread)
                for t in self.threads:
                    print(t.is_alive())

        except KeyboardInterrupt:
            self.stop()
    # остановка
    def stop(self):
        self.running = False
        self.server_socket.close()
        for t in self.threads:
            t.join()
        print("Server stopped.")



# Пример использования
if __name__ == '__main__':
    app = WebServer(port=2025)

    @app.get('/')
    def index(req):
        return Response(200, '<h1>Hello from WebServer!</h1>')

    @app.post('/submit')
    def submit(req):
        return Response(200, f'Received POST with body: {req.body}')
    # для проверки используем test.html

    app.handle_file('/file', 'tests/example.html')
    app.handle_file('/style.css', 'tests/style.css')
    app.handle_file('/script.js', 'tests/script.js')

    app.handle_dir('/files', 'C:/Users/Misha/PycharmProjects/PythonProject2/tests')

    app.start()
