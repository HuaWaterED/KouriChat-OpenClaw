## 用户信息
- **开发者**: 花水终
- **语言**: 中文优先
- **风格**: 简洁直接，不喜欢冗长总结

## 行动准则

**每次操作前必须说明要做什么，不能闷头干活。**
- 修改代码前：说明"我要修改 X 文件，改为 Y"
- 执行命令前：说明"我要执行 Z 命令"
- 启动/停止进程前：说明

**看代码前必须先 git pull**

## Git 规则
- 每次改动后立即推送，格式：`feat: ClaudeCode: 中文描述`
- push 前先 pull 以更新子仓库 commit
- commit 信息使用中文

## 推送后处理
1. git push 完成后
2. 杀死旧进程
3. 启动新进程
4. **必须等待日志出现才能确认启动成功**

## 搜索规则
**不要使用 WebSearch 工具**，必须使用 curl 调用 MiniMax 搜索 API：
```bash
curl -s -X POST "https://api.minimaxi.com/v1/coding_plan/search" \
  -H "Authorization: Bearer sk-cp-2o2aQCiH5-fL1RZOCERBE1XWD8KEa_gncxZdpztWdLFVuXr8bQ-MqNKGZAKDskrnK2JH8rYhfj4B85U5w81MU-cHPW48OZxcQht405SetLj4WsMQ2dxu0Kc" \
  -H "Content-Type: application/json" \
  -d '{"q": "搜索关键词"}'
```
