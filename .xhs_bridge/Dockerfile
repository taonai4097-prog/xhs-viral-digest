# 用官方 playwright 镜像，预装浏览器，彻底规避 driver 404（vmxmy Go 二进制的死穴）
FROM mcr.microsoft.com/playwright:v1.62.1-jammy

WORKDIR /app

# 依赖先于源码复制，利用层缓存
COPY package.json ./
# 镜像已含浏览器，跳过再次下载
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
RUN npm install --omit=dev

COPY . .

ENV BRIDGE_PORT=18070
ENV BRIDGE_HEADLESS=true
EXPOSE 18070

# /ready 只探测二进制不启动浏览器，适合容器健康检查
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD node -e "const p=process.env.BRIDGE_PORT||18070;require('http').get('http://localhost:'+p+'/api/v1/ready',r=>process.exit(r.statusCode===200?0:1)).on('error',()=>process.exit(1))"

CMD ["node", "bridge.js"]
