import json
import re
import brotli
import gzip
import io
from bs4 import BeautifulSoup
import hashlib
import os
from pymongo import MongoClient
from datetime import datetime
from dotenv import load_dotenv()

load_dotenv()

# MongoDB 配置
MONGO_CONNECTION_STRING = os.environ.get("DATABASE_BASE_URL", "mongodb://localhost:27017/")
MONGO_DB_NAME = "google_filter_logs"
MONGO_COLLECTION_NAME = "filtered_items"

# 初始化MongoDB连接
try:
    mongo_client = MongoClient(MONGO_CONNECTION_STRING)
    db = mongo_client[MONGO_DB_NAME]
    collection = db[MONGO_COLLECTION_NAME]
except Exception as e:
    print(f"Failed to connect to MongoDB: {e}")
    collection = None

TARGET_CONTAINERS = [
    {
        # 容器选择器
        'container': 'div.s6JM6d.ufC5Cb',
        # 要删除的元素选择器列表
        'remove_rules': [
            'div.xfX4Ac.JI5uCe.qB9BY.yWNJXb.qzPQNd',
            'div.xfX4Ac.JI5uCe.qB9BY.yWNJXb.tQtKhb',
            'div.PmEWq.wHYlTd.vt6azd.Ww4FFb',
            'div.SoaBEf'
        ],
        'preserve_rules': []
    },
    {   # 过滤people also ask 下的内容
        'container': 'div.LQCGqc',
        'remove_rules': [
            'div[jsname="yEVEwb"]',
        ],
        'preserve_rules': []
    },
    { # 过滤全部页面下的video下的内容
        'container': 'div.Ea5p3b',
        'remove_rules': [
            'div.sHEJob',
        ],
        'preserve_rules': []
    },
    {  # 过滤people also search for 下的内容
        'container': 'div.AJLUJb',
        'remove_rules': [
            'div.b2Rnsc.vIifob',
        ],
        'preserve_rules': []
    },
    {
        'container': 'div.MjjYud ',
        'remove_rules': [
            'div.wHYlTd.Ww4FFb.vt6azd.tF2Cxc.asEBEc' # # 过滤 Forums 和web 页面下的内容
        ],
        'preserve_rules': []
    },
    {   # 过滤侧边栏下的内容
        'container': 'div.MBdbL',
        'remove_rules': [
            'div.vNFaUb.uJyGcf',
        ],
        'preserve_rules': []
    },
    {  #过滤video页面
        'container': 'div.MjjYud > div ',
        'remove_rules': [
            'div.PmEWq.wHYlTd.vt6azd.Ww4FFb',
        ],
        'preserve_rules': []
    },
    {   #过滤book页面
        'container': 'div[data-hveid="CAMQAA"]',
        'remove_rules': [
            'div.Yr5TG',
        ],
        'preserve_rules': []
    },
    {
        # 过滤侧边栏
        'container': 'div.A6K0A.z4oRIf',
        'remove_rules': [
            'div.osrp-blk',
            'div.ISATce.OIlTb.VmgTu.QAokWb.PZPZlff',
            'div.xGj8Mb',
            'div.vNFaUb.uJyGcf',
            'div.DoxwDb',
            'div.VelOt',
        ],
        'preserve_rules': []
    },
        {
        # 过滤侧边栏
        'container': 'div.ULSxyf',
        'remove_rules': [
            'div.vCUuC',
        ],
        'preserve_rules': []
    },
        {
        # 过滤侧边栏
        'container': 'div.JCZQSb',
        'remove_rules': [
            'div.xGj8Mb',
        ],
        'preserve_rules': []
    },
        {
        # 过滤联想搜索
        'container': 'div.HdbW6.MjUjnf.VM6qJ',
        'remove_rules': [
            'div.hHq9Z',
        ],
        'preserve_rules': []
    },
        {
        # 过滤book页面
        'container': 'div.xfX4Ac.JI5uCe.qB9BY.yWNJXb',
        'remove_rules': [
            'div.XRVJtc.bnmjfe.aKByQb',
        ],
        'preserve_rules': []
    }

]

VIDEO_PAGE_CONFIG = {
    'container': 'div.MjjYud > div',
    'remove_rules': [
        'div.PmEWq.wHYlTd.vt6azd.Ww4FFb',
    ],
    'preserve_rules': []
}

def log_to_mongo(data):
    """将数据记录到MongoDB"""
    if collection is None:
        return

    try:
        data["timestamp"] = datetime.utcnow()
        collection.insert_one(data)
    except Exception as e:
        print(f"Failed to log to MongoDB: {e}")

def filter_vet_response(response, filter_words):
    """专门处理 google.com/search?vet= 的响应包"""
    if not response:
        return None


    try:
        # 解码响应体
        body_text = response
        # 使用BeautifulSoup解析
        soup = BeautifulSoup(body_text, 'html.parser')

        # 定位目标容器
        containers = soup.select(VIDEO_PAGE_CONFIG['container'])
        pattern = re.compile('|'.join(filter_words), flags=re.IGNORECASE)

        removed_count = 0
        for container in containers:
            # 检查是否在保留规则中
            if any(container.select(preserve) for preserve in VIDEO_PAGE_CONFIG['preserve_rules']):
                continue

            # 检查是否匹配删除规则
            if any(container.select(rule) for rule in VIDEO_PAGE_CONFIG['remove_rules']):
                # 关键词检查
                text_content = container.get_text()
                if pattern.search(text_content):
                    # 记录删除的过滤条目
                    log_to_mongo({
                        "type": "vet_page_filter",
                        "action": "removed_container",
                        "content": str(container),
                        "filter_words": filter_words,
                        "container_selector": VIDEO_PAGE_CONFIG['container'],
                        "remove_rules": VIDEO_PAGE_CONFIG['remove_rules']
                    })

                    container.decompose()  # 删除整个DOM块
                    removed_count += 1

        if removed_count > 0:
            print(f"已删除 {removed_count} 个包含关键词的区块")
            # 生成新HTML并编码
            filtered_body = str(soup)
            new_body = filtered_body.encode('utf-8')
        else:
            print("未检测到需要删除的内容")

        return new_body
    except Exception as e:
        print(f"处理失败: {str(e)}")
        return response  # 返回原始响应体

def google_search_filter(response,filter_words):
    """
    过滤谷歌联想词的函数
    :param response: 响应对象
    :param filter_words: 需要过滤的词列表
    """
    decompressed = response
    prefix = b")]}'\n"
    # if decompressed.startswith(prefix):
    #     json_bytes = decompressed[len(prefix):]
    # else:
    #     json_bytes = decompressed
    data = json.loads(decompressed[len(prefix):])
    filtered = []
    for item in data[0]:
        text = item[0]
        if not any(re.search(word, text) for word in filter_words):
            filtered.append(item)
        else:
            print(f"Filtered out: {text}")
            # 记录删除的过滤条目
            log_to_mongo({
                "type": "search_suggestion",
                "action": "filtered",
                "text": text,
                "filter_words": filter_words,
                "original_data": item
            })
    data[0] = filtered
    new_json = json.dumps(data, ensure_ascii=False).encode("utf-8")
    new_body = prefix + new_json
    return new_body

def google_search_page_filter(response, filter_words):
    """
    多目标深度删除
    :param response: 响应对象
    :param filter_words: 需要过滤的词列表
    """
    soup = BeautifulSoup(response, 'html.parser')
    total_removed = 0

    # 创建关键词正则表达式
    pattern = re.compile('|'.join(filter_words), re.IGNORECASE)

    # 处理每个目标容器
    for container_config in TARGET_CONTAINERS:
        container_selector = container_config['container']
        containers = soup.select(container_selector)

        if not containers:
            # print(f"未找到容器: {container_selector}")
            continue

        # print(f"\n处理容器: {container_selector}")
        container_removed = 0

        for container in containers:
            # 先标记要保留的元素
            preserved_elements = []
            for preserve_rule in container_config['preserve_rules']:
                preserved_elements.extend(container.select(preserve_rule))

            # 处理每个删除规则
            for remove_rule in container_config['remove_rules']:
                for element in container.select(remove_rule):
                    # 检查是否在保留列表中
                    if element in preserved_elements:
                        continue

                    # 检查是否包含关键词
                    if element.find(string=pattern):
                        # 获取元素信息
                        element_info = {
                            'tag': element.name,
                            'classes': element.get('class', []),
                            'id': element.get('id'),
                            'rule': remove_rule,
                            'container': container_selector
                        }

                        # 打印删除信息
                        print(f"删除元素 [规则: {remove_rule}]")
                        print(f"标签: {element_info['tag']}")
                        print(f"类: {element_info['classes']}")
                        print(f"内容: {str(element)}")
                        print("-" * 40)
                        # 记录删除的过滤条目
                        log_to_mongo({
                            "type": "search_page_filter",
                            "action": "removed_element",
                            "element_info": element_info,
                            "filter_words": filter_words,
                            "container_config": container_config
                        })

                        # 删除元素
                        element.decompose()
                        container_removed += 1
                        total_removed += 1

        # print(f"本容器删除元素数: {container_removed}")

    # print(f"\n总共删除 {total_removed} 个元素")

    modified_html = str(soup)
    return modified_html.encode('utf-8')

def google_search_video_page_filter(response, filter_words):
    """
    多目标深度删除
    :param response: 响应对象
    :param filter_words: 需要过滤的词列表
    """
    soup = BeautifulSoup(response, 'html.parser')
    total_removed = 0

    # 创建关键词正则表达式
    pattern = re.compile('|'.join(filter_words), re.IGNORECASE)

    # 处理每个目标容器
    for container_config in VIDEO_PAGE_CONFIG:
        container_selector = container_config['container']
        containers = soup.select(container_selector)

        if not containers:
            # print(f"未找到容器: {container_selector}")
            continue

        for container in containers:
            # 先标记要保留的元素
            preserved_elements = []
            for preserve_rule in container_config['preserve_rules']:
                preserved_elements.extend(container.select(preserve_rule))

            # 处理每个删除规则
            for remove_rule in container_config['remove_rules']:
                for element in container.select(remove_rule):
                    # 检查是否在保留列表中
                    if element in preserved_elements:
                        continue

                    # 检查是否包含关键词
                    if element.find(string=pattern):
                        # 获取元素信息
                        element_info = {
                            'tag': element.name,
                            'classes': element.get('class', []),
                            'id': element.get('id'),
                            'rule': remove_rule,
                            'container': container_selector
                        }

                        # 打印删除信息
                        print(f"删除元素 [规则: {remove_rule}]")
                        print(f"标签: {element_info['tag']}")
                        print(f"类: {element_info['classes']}")
                        print(f"ID: {element_info['id']}")
                        print("-" * 40)
                        # 记录删除的过滤条目
                        log_to_mongo({
                            "type": "video_page_filter",
                            "action": "removed_element",
                            "element_info": element_info,
                            "filter_words": filter_words,
                            "container_config": container_config
                        })

                        # 删除元素
                        element.decompose()
                        total_removed += 1

        # print(f"本容器删除元素数: {container_removed}")

    # print(f"\n总共删除 {total_removed} 个元素")

    modified_html = str(soup)
    return modified_html.encode('utf-8')

def get_decoded_body(response):
    encoding = response.headers.get('content-encoding', '').lower()
    body = response.body
    if encoding == 'br':
        try:
            return brotli.decompress(body)
        except Exception as e:
            print(f"[get_decoded_body] brotli解压失败: {e}")
            return b""
    elif encoding == 'gzip':
        try:
            return gzip.decompress(body)
        except Exception as e:
            print(f"[get_decoded_body] gzip解压失败: {e}")
            return b""
    elif encoding == 'deflate':
        try:
            return io.BytesIO(body).read()
        except Exception as e:
            print(f"[get_decoded_body] deflate解压失败: {e}")
            return b""
    else:
        return body if body else b""
    
def calculate_hash(content):
# """计算内容的哈希值"""
    return hashlib.md5(content.encode('utf-8')).hexdigest()
