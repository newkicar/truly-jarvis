"""配置加载。

读取 .env（BASE_URL/API_KEY/MODEL_ID/TAVILY_KEY，注意当前为 ':' 分隔小写，需自定义解析）与 javis.json。
产出配置 dataclass。可变项均来自 javis.json，不写死。
"""
