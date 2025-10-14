import socket
import struct
import sys
import os
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

MULTICAST_GROUP = 'ff02::1'
PORT = 57681
KEY = ChaCha20Poly1305.generate_key()  # 实际应用中请安全保存和分发

class ChaCha20AEAD:
    def __init__(self, key: bytes):
        self.chacha = ChaCha20Poly1305(key)

    def encrypt(self, plaintext: bytes) -> bytes:
        nonce = os.urandom(12)
        ciphertext = self.chacha.encrypt(nonce, plaintext, None)
        return nonce + ciphertext  # 返回nonce+密文

    def decrypt(self, data: bytes) -> bytes:
        nonce = data[:12]
        ciphertext = data[12:]
        return self.chacha.decrypt(nonce, ciphertext, None)

def server():
    sock = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
    sock.bind(('::', PORT))
    group_bin = socket.inet_pton(socket.AF_INET6, MULTICAST_GROUP)
    mreq = group_bin + struct.pack('@I', 0)
    sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_JOIN_GROUP, mreq)
    aead = ChaCha20AEAD(KEY)
    print("服务端已启动，等待接收加密消息...")
    while True:
        data, addr = sock.recvfrom(4096)
        try:
            msg = aead.decrypt(data)
            print(f"收到来自{addr}的消息: {msg.decode()}")
        except Exception as e:
            print("解密失败:", e)

def client():
    sock = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
    sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_MULTICAST_HOPS, 1)
    aead = ChaCha20AEAD(KEY)
    while True:
        msg = input("输入要发送的消息: ").encode()
        encrypted = aead.encrypt(msg)
        sock.sendto(encrypted, (MULTICAST_GROUP, PORT))
        print("已发送加密消息。")

def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ('server', 'client'):
        print("用法: python main.py server|client")
        return
    if sys.argv[1] == 'server':
        server()
    else:
        client()

if __name__ == "__main__":
    main()
