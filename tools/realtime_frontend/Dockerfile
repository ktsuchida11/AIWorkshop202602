FROM node:18-slim
WORKDIR /app

# Install dependencies
COPY package.json package-lock.json* ./
RUN npm install --production=false

# Copy source code
COPY . .

# Install a lightweight HTTP server (e.g., serve)
RUN npm install -g serve

# React アプリをビルド
RUN npm run build

# Expose the port and set the default command
EXPOSE 5173
CMD ["serve", "-s", "build", "-l", "5173"]