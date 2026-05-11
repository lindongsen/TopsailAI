# API Key and Environs

Table: api_key_environs

Column:
    - api_key_id
    - key
    - value

api_key和environment variables 建立关系，可以为api_key设定一些环境变量。

api_key会和session绑定关系（table api_key_session），当处理session的时候，就可以通过这个关系找到 api_key。
如果有api_key，就能找到 api_key对应的环境变量信息。
如果有环境变量信息，当调用命令行时，则使用这些环境变量，如：processor, summarizer, checker etc..
