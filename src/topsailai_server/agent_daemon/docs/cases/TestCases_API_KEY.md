# Integration Test for API Key

## TOPSAILAI_AGENT_DAEMON_API_KEY_ENABLED=false

功能一切正常，是否配置了 API Key 都没有影响

## TOPSAILAI_AGENT_DAEMON_API_KEY_ENABLED=true

1. 服务启动后，检查到没有admin key的时候，会自动初始化一个admin key。如果环境变量配置了 `TOPSAILAI_AGENT_DAEMON_DEFAULT_ADMIN_KEY` 就用它注册到 api_key，否则就随机生成。
2. 使用 admin 的api_key可以创建 更多api key，包括：admin 和 user 角色，能查到所有的资源。
3. user 的api_key只能使用，不能对api_key做任何修改，也不能创建新的api key；只能查到 api_key 所绑定的关系资源，如 session。
