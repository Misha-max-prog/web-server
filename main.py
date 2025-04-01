import socket

# http://127.0.0.1:2025/request
server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.bind(('127.0.0.1', 2025))
server.listen(5)
print('Let`s go...')
client_socket, address = server.accept()
while True:
    data = client_socket.recv(1024).decode('utf-8')
    print(data)
    HDRS = 'HTTP/1.1 200 OK\r\nContent-type: text/html; charset=utf-8\r\n\r\n'
    content = 'Здарова брат'.encode('utf-8')
    client_socket.send(HDRS.encode('utf-8') + content)
    client_socket.close()


