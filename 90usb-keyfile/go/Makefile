.PHONY: build clean

build:
	GOOS=linux GOARCH=amd64 go build -ldflags="-s -w" -o usb-keyfile usb-keyfile.go

clean:
	rm -f usb-keyfile