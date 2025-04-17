import selectors
import socket
import threading
import re
import os
from urllib.parse import unquote

debug = 1
# немного ооп вам в ленту
class HTTPError(Exception):
    def __init__(self, status_code, message=None):
        self.status_code = status_code
        self.message = message or self.default_message
        super().__init__(self.message)

    @property
    def default_message(self):
        return {
            400: 'Bad Request',
            401: 'Unauthorized',
            403: 'Forbidden',
            404: 'Not Found',
            500: 'Internal Server Error'
        }.get(self.status_code, 'Unknown Error')

class BadRequestError(HTTPError):
    def __init__(self, message=None):
        super().__init__(400, message)


class NotFoundError(HTTPError):
    def __init__(self, message=None):
        super().__init__(404, message)


class InternalServerError(HTTPError):
    def __init__(self, message=None):
        super().__init__(500, message)


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
        reason = {
            200: 'OK',
            301: 'Moved Permanently',
            302: 'Found',
            304: 'Not Modified',
            400: 'Bad Request',
            401: 'Unauthorized',
            403: 'Forbidden',
            404: 'Not Found',
            500: 'Internal Server Error',
            503: 'Service Unavailable'
        }.get(self.status_code, 'OK')
        headers = ''.join(f'{k}: {v}\r\n' for k, v in self.headers.items())
        return f'HTTP/1.1 {self.status_code} {reason}\r\n{headers}\r\n{self.body}'.encode()
# редирект на новую страничку
class RedirectResponse(Response):
    def __init__(self, location, permanent=False):
        headers = {'Location': location}
        status_code = 301 if permanent else 302
        super().__init__(status_code, '', headers)

class WebServer:
    def __init__(self, host='localhost', port=8080, hostname=None, max_threads=10):
        self.host = host
        self.port = port
        self.hostname = hostname or host
        self.max_threads = max_threads
        self.routes = {'GET': [], 'POST': [], 'PUT': [], 'DELETE': [], 'PATCH': []}
        self.file_routes = {}
        self.dir_routes = {}
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) # магия которая позволяет переиспользовать порт
        self.running = False
        self.threads = []
        self.selector = selectors.DefaultSelector() # потому что так написано в документации библиотеки :)
        self.stop_event = threading.Event()

    # регистрация обработчиков
    def get(self, path):
        return self._add_route('GET', path)

    def post(self, path):
        return self._add_route('POST', path)

    def put(self, path):
        return self._add_route('PUT', path)

    def delete(self, path):
        return self._add_route('DELETE', path)

    def patch(self, path):
        return self._add_route('PATCH', path)

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
            if debug:
                print(request_data)
            if not request_data:
                return
            request = self._parse_request(request_data)
            if not request:
                response = self._error_response(400, 'Invalid request format')
                client_socket.sendall(response.to_http())
                return

            response = self._dispatch(request)
            client_socket.sendall(response.to_http())
        finally:
            client_socket.close()

    # находим, кто должен обработать запрос
    def _dispatch(self, request):
        try:
            method_routes = self.routes.get(request.method, [])
            for pattern, handler in method_routes:
                match = pattern.match(request.path)
                if match:
                    try:
                        return handler(request)
                    except HTTPError as e:
                        return self._error_response(e.status_code, e.message)
                    except Exception as e:
                        print(f"Handler error: {e}")
                        return self._error_response(500, str(e))

            # обработка GET
            if request.method == 'GET':
                if request.path in self.file_routes:
                    return self._serve_file(self.file_routes[request.path])
                for route, folder in self.dir_routes.items():
                    if request.path.startswith(route):
                        return self._serve_dir(folder, request.path[len(route):])

            # метод не поддерживается на сервере
            if request.method in self.routes and request.path in [p for p, _ in self.routes[request.method]]:
                return self._error_response(405, 'Method Not Allowed')

            return self._error_response(404)
        except Exception as e:
            print(f"Dispatch error: {e}")
            return self._error_response(500, str(e))

    # отдаём файл
    def _serve_file(self, path):
        try:
            if not os.path.exists(path):
                return self._error_response(404, 'File not found')

            # проверка файла на текст
            text_extensions = {'.html', '.css', '.js', '.txt', '.json', '.xml'}
            is_text = any(path.endswith(ext) for ext in text_extensions)

            if is_text:
                with open(path, 'r', encoding='utf-8') as f:
                    body = f.read()
            else:
                with open(path, 'rb') as f:
                    body = f.read()

            content_type = self._guess_type(path)
            return Response(200, body, {'Content-Type': content_type})
        # отказано в доступе
        except PermissionError:
            return self._error_response(403, 'Forbidden')
        except Exception as e:
            print(f"File serving error: {e}")
            return self._error_response(500, str(e))

    # отдаём содержимое папки или файл из неё
    def _serve_dir(self, dir_path, sub_path):
        full_path = os.path.join(dir_path, sub_path.lstrip('/'))
        if not os.path.exists(full_path):
            return self._error_response(404, 'Not found')

        if os.path.isdir(full_path):
            try:
                files = os.listdir(full_path)
                body = '<html><head><title>Directory Listing</title></head><body><h1>Directory Listing</h1><ul>'
                for file in files:
                    file_path = os.path.join(sub_path.lstrip('/'), file)
                    body += f'<li><a href="{file_path}">{file}</a></li>'
                body += '</ul></body></html>'
                return Response(200, body)
            except PermissionError:
                return self._error_response(403, 'Forbidden')
        else:
            return self._serve_file(full_path)

    # обработка ошибок
    def _error_response(self, status_code, message=None):
        error_pages = {
            400: 'errors/400.html',
            401: 'errors/401.html',
            403: 'errors/403.html',
            404: 'errors/404.html',
            405: 'errors/405.html',
            500: 'errors/500.html',
            503: 'errors/503.html'
        }

        # подгружение странички ошибки
        if status_code in error_pages and os.path.exists(error_pages[status_code]):
            try:
                with open(error_pages[status_code], 'r', encoding='utf-8') as f:
                    body = f.read()
                return Response(status_code, body)
            except Exception as e:
                print(f"Error loading custom error page: {e}")

        # создание дефолтной странички ошибки если пользователь не создал
        body = f"""
        <!DOCTYPE html>
        <html>
            <head>
                <title>{status_code} Error</title>
                <style>
                    body {{ font-family: Arial, sans-serif; line-height: 1.6; margin: 0; padding: 20px; }}
                    .container {{ max-width: 800px; margin: 0 auto; }}
                    h1 {{ color: #d32f2f; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <h1>{status_code} Error</h1>
                    <p>{message or 'An error occurred while processing your request.'}</p>
                </div>
            </body>
        </html>
        """
        return Response(status_code, body)

    # определяем тип файла
    def _guess_type(self, filename):
        content_types = {
            '.html': 'text/html; charset=utf-8',
            '.htm': 'text/html; charset=utf-8',
            '.css': 'text/css; charset=utf-8',
            '.js': 'application/javascript; charset=utf-8',
            '.json': 'application/json; charset=utf-8',
            '.xml': 'application/xml; charset=utf-8',
            '.txt': 'text/plain; charset=utf-8',
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.gif': 'image/gif',
            '.svg': 'image/svg+xml',
            '.ico': 'image/x-icon',
            '.pdf': 'application/pdf',
            '.zip': 'application/zip',
            '.gz': 'application/gzip',
            '.mp3': 'audio/mpeg',
            '.mp4': 'video/mp4',
            '.webm': 'video/webm',
            '.woff': 'font/woff',
            '.woff2': 'font/woff2',
            '.ttf': 'font/ttf',
            '.otf': 'font/otf'
        }

        ext = os.path.splitext(filename)[1].lower()
        return content_types.get(ext)

    # запуск
    def start(self):
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(5)
        self.running = True
        print(f'Serving on http://{self.host}:{self.port}')

        self.selector.register(self.server_socket, selectors.EVENT_READ, self._accept)

        try:
            while self.running:
                events = self.selector.select(timeout=1)
                for key, mask in events:
                    callback = key.data
                    callback(key.fileobj)

                # Clean up finished threads
                self.threads = [t for t in self.threads if t.is_alive()]

                if self.stop_event.is_set():
                    self.running = False

        except KeyboardInterrupt:
            print("\nServer interrupted by user")
            self.stop()
        except Exception as e:
            print(f"Server error: {e}")
            self.stop()
        finally:
            self.selector.close()
            self.server_socket.close()

    def _accept(self, sock):
        try:
            client_socket, addr = sock.accept()
            print(f"Connection accepted from {addr}")
            thread = threading.Thread(target=self._handle_client, args=(client_socket,))
            thread.daemon = True
            thread.start()
            self.threads.append(thread)
        except OSError as e:
            if self.running:
                print(f"Error accepting connection: {e}")
    # остановка
    def stop(self):
        print("Shutting down server...")
        self.running = False
        self.stop_event.set()

        for thread in self.threads:
            if thread.is_alive():
                thread.join(timeout=1.0)

        self.server_socket.close()
        print("Server stopped.")



# Пример использования
if __name__ == '__main__':
    # созадем папку ошибок
    if not os.path.exists('errors'):
        os.makedirs('errors')

    # для шаблона ошибки
    error_pages = {
        '400.html': 'Bad Request - The server cannot process the request due to client error',
        '401.html': 'Unauthorized - Authentication is required',
        '403.html': 'Forbidden - You don\'t have permission to access this resource',
        '404.html': 'Not Found - The requested resource was not found',
        '405.html': 'Method Not Allowed - The request method is not supported',
        '500.html': 'Internal Server Error - The server encountered an unexpected condition',
        '503.html': 'Service Unavailable - The server is not ready to handle the request'
    }
    # создаем странички ошибок на нашем сервере как юзер
    for filename, content in error_pages.items():
        path = os.path.join('errors', filename)
        if not os.path.exists(path):
            with open(path, 'w', encoding='utf-8') as f:
                f.write(f"""
                <!DOCTYPE html>
                <html>
                    <head>
                        <title>{filename.split('.')[0]} Error</title>
                        <style>
                            body {{ font-family: Arial, sans-serif; line-height: 1.6; margin: 0; padding: 20px; }}
                            .container {{ max-width: 800px; margin: 0 auto; }}
                            h1 {{ color: #d32f2f; }}
                        </style>
                    </head>
                    <body>
                        <div class="container">
                            <h1>{filename.split('.')[0]} Error</h1>
                            <p>{content}</p>
                        </div>
                    </body>
                </html>
                """)
    app = WebServer(port=2025)

    @app.get('/')
    def index(req):
        return Response(200, """
        <!DOCTYPE html>
        <html>
            <head>
                <title>WebServer Home</title>
                <style>
                    body { font-family: Arial, sans-serif; line-height: 1.6; margin: 0; padding: 20px; }
                    .container { max-width: 800px; margin: 0 auto; }
                    h1 { color: #2c3e50; }
                    .links { margin-top: 20px; }
                    .links a { display: inline-block; margin-right: 15px; color: #3498db; text-decoration: none; }
                    .links a:hover { text-decoration: underline; }
                </style>
            </head>
            <body>
                <div class="container">
                    <h1>Welcome to WebServer</h1>
                    <p>This is a simple web server implemented in Python.</p>

                    <div class="links">
                        <h3>Example Routes:</h3>
                        <a href="/hello">Hello World</a>
                        <a href="/redirect">Redirect Example</a>
                        <a href="/redirect">Redirect Example</a>
                        <a href="/error">Error Example</a>
                        <a href="/nonexistent">404 Example</a>
                        <a href="/files">Directory Listing</a>
                    </div>
                </div>
            </body>
        </html>
        """)


    @app.get('/hello')
    def hello(req):
        return Response(200, '<h1>Hello, World!</h1><p>This is a simple route example.</p>')


    @app.get('/redirect')
    def redirect(req):
        return RedirectResponse('/hello')


    @app.get('/permanent-redirect')
    def permanent_redirect(req):
        return RedirectResponse('/hello', permanent=True)


    @app.get('/error')
    def error(req):
        raise InternalServerError("This is a simulated server error")


    @app.post('/submit')
    def submit(req):
        return Response(200, f'<h1>Form Submitted</h1><p>Received: {req.body}</p>')
    # для проверки используем test.html

    app.handle_file('/file', 'tests/example.html')
    app.handle_file('/style.css', 'tests/style.css')
    app.handle_file('/script.js', 'tests/script.js')
    app.handle_file('/images.jpg', 'tests/images.jpg') # все еще нифига не робит
    app.handle_dir('/files', 'tests')

    app.start()
