FROM node:18-slim
WORKDIR /app

# package.jsonをコピーして一括インストール
COPY package.json package-lock.json* ./
RUN npm install

# ソースコードをコピー
COPY . .

# React アプリをビルド
RUN npm run build

# --- ディレクトリ構造をURLパス /k-okoshi/ に合わせる ---
RUN mkdir /tmp/build_assets && \
    mv build/* /tmp/build_assets/ && \
    mkdir -p build/k-okoshi && \
    mv /tmp/build_assets/* build/k-okoshi/

# serve.json を build の直下に配置
COPY serve.json ./build/

# HTTPサーバーのインストール
RUN npm install -g serve

EXPOSE 5173
# serve の公開ディレクトリを build に指定
CMD ["serve", "build", "-c", "serve.json", "-l", "5173"]