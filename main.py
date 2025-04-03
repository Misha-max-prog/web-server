import socket
import re


class MiniBottle:
    def __init__(self):
        self.routes = []

    def route(self, path, method='GET'):
        def decorator(func):
            self.routes.append((re.compile(f'^{path}$'), method, func))
            return func

        return decorator

    def handle_request(self, request):
        lines = request.split('\r\n')
        first_line = lines[0].split()
        if len(first_line) < 2:
            return 'HTTP/1.1 400 Bad Request\r\n\r\nBad Request'.encode('utf-8')

        method, path = first_line[0], first_line[1]

        for pattern, route_method, func in self.routes:
            if pattern.match(path) and method == route_method:
                response_body = func()
                return f'HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n\r\n{response_body}'.encode(
                    'utf-8')

        return 'HTTP/1.1 404 Not Found\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n404 Not Found'.encode('utf-8')

    def run(self, host='localhost', port=2025):
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.bind((host, port))
        server_socket.listen(1)
        print(f'Serving on http://{host}:{port}')

        while True:
            client_socket, addr = server_socket.accept()
            print(f'Incoming request from {addr}')
            request = client_socket.recv(1024).decode('utf-8')
            response = self.handle_request(request)
            client_socket.sendall(response)
            client_socket.close()


# Пример использования
app = MiniBottle()


@app.route('/')
def home():
    return 'Привет, мир!'


@app.route('/hello')
def hello():
    return 'Да тут типо ветвление возможно'


if __name__ == '__main__':
    app.run()
