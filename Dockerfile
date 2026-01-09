FROM python:3.12-slim

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    jq \
    golang-go \
    && rm -rf /var/lib/apt/lists/*

# Install goat
ENV GOPATH=/root/go
ENV PATH=$PATH:/root/go/bin
RUN go install github.com/bluesky-social/indigo/cmd/goat@latest

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN python -m spacy download en_core_web_lg

# Clone bluesky-tools
RUN git clone https://github.com/Lucent/bluesky-tools.git

# App files
COPY app.py my_ld.py fetch_repo.sh ./
RUN chmod +x fetch_repo.sh

RUN mkdir -p account_dumps

EXPOSE 5000

CMD ["gunicorn", "-w", "1", "--threads", "4", "-b", "0.0.0.0:5000", "app:app"]
