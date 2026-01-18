import asyncio
import aiohttp
import logging
import json
from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field, ValidationError
from datetime import datetime

# --- 配置日志 ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("sms_manager.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("SMSManager")

# --- 核心枚举与数据模型 ---

class ProviderType(Enum):
    SMS_MAN = "sms-man"
    FIVE_SIM = "5sim"
    VAK_SMS = "vak-sms"

class RentStatus(Enum):
    WAITING = "waiting"     # 等待短信
    RECEIVED = "received"   # 收到短信
    FINISHED = "finished"   # 租用结束/完成
    TIMEOUT = "timeout"     # 超时/过期
    CANCELLED = "cancelled" # 已取消
    UNKNOWN = "unknown"

class SMSOrder(BaseModel):
    """统一的订单/租用数据模型"""
    order_id: str
    phone_number: str
    country: str
    service: str
    provider: ProviderType
    status: RentStatus = RentStatus.WAITING
    sms_text: Optional[str] = None
    sms_code: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)
    expiration_time: Optional[datetime] = None

# --- 自定义异常 ---

class SMSException(Exception):
    """基础SMS异常"""
    pass

class BalanceError(SMSException):
    """余额不足"""
    pass

class NoNumberError(SMSException):
    """无可用号码"""
    pass

class APIRequestError(SMSException):
    """网络或API请求错误"""
    pass

# --- 抽象基类 ---

class BaseSMSProvider(ABC):
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = ""

    @abstractmethod
    async def get_balance(self) -> float:
        """查询余额"""
        pass

    @abstractmethod
    async def rent_number(self, country: str, service: str, duration: int = 4) -> SMSOrder:
        """
        租用号码
        :param country: 国家代码 (iso2, e.g., 'ru', 'us')
        :param service: 服务代码 (e.g., 'tg', 'go')
        :param duration: 租用时长 (单位通常为小时或平台特定单位)
        """
        pass

    @abstractmethod
    async def check_sms(self, order: SMSOrder) -> SMSOrder:
        """检查是否有新短信更新订单状态"""
        pass

    @abstractmethod
    async def cancel_rent(self, order_id: str) -> bool:
        """取消租用"""
        pass

    async def _make_request(self, method: str, url: str, params: dict = None, headers: dict = None, json_data: dict = None) -> Dict:
        """统一的异步请求处理"""
        async with aiohttp.ClientSession() as session:
            try:
                async with session.request(method, url, params=params, headers=headers, json=json_data) as response:
                    content_type = response.headers.get('Content-Type', '')
                    
                    if response.status >= 400:
                        text = await response.text()
                        logger.error(f"API Error [{response.status}] {url}: {text}")
                        raise APIRequestError(f"API returned {response.status}: {text}")

                    if 'application/json' in content_type:
                        return await response.json()
                    else:
                        # 处理某些API返回纯文本的情况
                        text = await response.text()
                        try:
                            return json.loads(text)
                        except json.JSONDecodeError:
                            return {"text_response": text}
            except aiohttp.ClientError as e:
                logger.error(f"Network error requesting {url}: {str(e)}")
                raise APIRequestError(f"Network error: {str(e)}")

# --- 具体实现: SMS-Man ---

class SMSManProvider(BaseSMSProvider):
    def __init__(self, api_key: str):
        super().__init__(api_key)
        self.base_url = "https://api.sms-man.com/rent-api"

    async def get_balance(self) -> float:
        # SMS-Man Rent API 的余额通常和主站通用，但文档主要列出了 rent 的操作
        # 这里使用主 API 获取余额
        url = "http://api.sms-man.com/control/get-balance"
        data = await self._make_request("GET", url, params={"token": self.api_key})
        # 格式通常是 {"balance": "100.50"}
        return float(data.get("balance", 0.0))

    async def rent_number(self, country: str, service: str, duration: int = 4) -> SMSOrder:
        # 注意：SMS-Man 需要将国家和服务的 string 转换为内部 ID。
        # 为简化，这里假设调用者知道 ID，或者实际项目中需要做一个 Mapping 字典。
        # 此处演示直接调用，需要自行维护 country_id 和 service_id 的映射。
        # 假设 country='us' -> id 3 (示例), service='tg' -> id 1 (示例)
        # 实际开发中建议先调用 /get-countries 和 /get-services 获取映射
        
        url = f"{self.base_url}/get-number"
        # 警告：SMS-Man API 参数非常依赖 ID，这里仅作逻辑演示，实际需传入数字 ID
        params = {
            "token": self.api_key,
            "country_id": country,  # 用户需传入 ID
            "service_id": service,  # 用户需传入 ID
            "time": duration * 60   # 假设单位是分钟
        }
        
        logger.info(f"Requesting SMS-Man Rent: {params}")
        resp = await self._make_request("GET", url, params=params)
        
        # 响应示例: {"request_id": 12345, "number": "123456789", ...}
        if "error_code" in resp:
            raise APIRequestError(f"SMS-Man Error: {resp.get('error_msg')}")
            
        return SMSOrder(
            order_id=str(resp["request_id"]),
            phone_number=resp["number"],
            country=str(country),
            service=str(service),
            provider=ProviderType.SMS_MAN
        )

    async def check_sms(self, order: SMSOrder) -> SMSOrder:
        url = f"{self.base_url}/get-sms"
        params = {"token": self.api_key, "request_id": order.order_id}
        
        resp = await self._make_request("GET", url, params=params)
        
        # 假设响应是一个列表或包含 sms 字段
        # SMS-Man Rent API 返回结构可能较复杂，需根据实际文档调整
        # 这里模拟收到短信
        if isinstance(resp, list) and len(resp) > 0:
            last_sms = resp[-1] # 获取最新一条
            order.sms_text = last_sms.get("text")
            order.sms_code = last_sms.get("code")
            order.status = RentStatus.RECEIVED
        
        return order

    async def cancel_rent(self, order_id: str) -> bool:
        url = f"{self.base_url}/set-status"
        # status 2 usually means close/cancel in many APIs, check documentation
        params = {"token": self.api_key, "request_id": order_id, "status": 2}
        await self._make_request("GET", url, params=params)
        return True

# --- 具体实现: 5SIM ---

class FiveSimProvider(BaseSMSProvider):
    def __init__(self, api_key: str):
        super().__init__(api_key)
        self.base_url = "https://5sim.net/v1"
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json"
        }

    async def get_balance(self) -> float:
        url = f"{self.base_url}/user/profile"
        data = await self._make_request("GET", url, headers=self.headers)
        return float(data.get("balance", 0.0))

    async def rent_number(self, country: str, service: str, duration: int = None) -> SMSOrder:
        # 5SIM 格式: /user/buy/hosting/{country}/{product}
        # 5SIM 的 Hosting 即为 Rent
        url = f"{self.base_url}/user/buy/hosting/{country}/{service}"
        
        logger.info(f"Requesting 5SIM Hosting: {url}")
        resp = await self._make_request("POST", url, headers=self.headers)
        
        # 5SIM 响应包含 id, phone 等
        if "id" not in resp:
            raise APIRequestError(f"5SIM Failed: {resp}")

        return SMSOrder(
            order_id=str(resp["id"]),
            phone_number=resp["phone"],
            country=country,
            service=service,
            provider=ProviderType.FIVE_SIM,
            expiration_time=resp.get("expires") # 5SIM 返回 ISO 时间
        )

    async def check_sms(self, order: SMSOrder) -> SMSOrder:
        # 5SIM 检查订单详情
        url = f"{self.base_url}/user/check/{order.order_id}"
        resp = await self._make_request("GET", url, headers=self.headers)
        
        sms_list = resp.get("sms", [])
        if sms_list:
            last_sms = sms_list[-1]
            order.sms_text = last_sms.get("text")
            order.sms_code = last_sms.get("code")
            order.status = RentStatus.RECEIVED
        
        if resp.get("status") == "FINISHED":
            order.status = RentStatus.FINISHED
        
        return order

    async def cancel_rent(self, order_id: str) -> bool:
        # 5SIM Hosting 通常不能立刻取消退款，或者是 finish
        url = f"{self.base_url}/user/finish/{order_id}"
        await self._make_request("GET", url, headers=self.headers)
        return True

# --- 具体实现: Vak-SMS ---

class VakSMSProvider(BaseSMSProvider):
    def __init__(self, api_key: str):
        super().__init__(api_key)
        self.base_url = "https://vak-sms.com/api"

    async def get_balance(self) -> float:
        url = f"{self.base_url}/getBalance/"
        resp = await self._make_request("GET", url, params={"apiKey": self.api_key})
        return float(resp.get("balance", 0.0))

    async def rent_number(self, country: str, service: str, duration: int = 4) -> SMSOrder:
        url = f"{self.base_url}/getNumber/"
        params = {
            "apiKey": self.api_key,
            "service": service,
            "country": country,
            "rent": "true" # 关键参数
        }
        
        logger.info(f"Requesting Vak-SMS Rent: {params}")
        resp = await self._make_request("GET", url, params=params)
        
        if "idNum" not in resp:
            error = resp.get("error", "Unknown error")
            if error == "no_numbers":
                raise NoNumberError("Vak-SMS: No numbers available")
            if error == "no_balance":
                raise BalanceError("Vak-SMS: Insufficient balance")
            raise APIRequestError(f"Vak-SMS Error: {error}")
            
        return SMSOrder(
            order_id=str(resp["idNum"]),
            phone_number=str(resp["tel"]),
            country=country,
            service=service,
            provider=ProviderType.VAK_SMS
        )

    async def check_sms(self, order: SMSOrder) -> SMSOrder:
        url = f"{self.base_url}/getSmsCode/"
        params = {"apiKey": self.api_key, "idNum": order.order_id}
        
        resp = await self._make_request("GET", url, params=params)
        
        # Vak-SMS returns {"smsCode": "..."} or {"error": "wait"}
        if "smsCode" in resp and resp["smsCode"]:
            order.sms_code = resp["smsCode"]
            order.status = RentStatus.RECEIVED
            # 尝试提取完整文本，Vak 有时候只给 code，有时候有 full text
            order.sms_text = resp.get("smsCode") 
        
        return order

    async def cancel_rent(self, order_id: str) -> bool:
        url = f"{self.base_url}/setStatus/"
        # status: end (finish), bad (cancel/refund if no code)
        params = {"apiKey": self.api_key, "idNum": order_id, "status": "end"}
        await self._make_request("GET", url, params=params)
        return True

# --- 工厂管理类 ---

class SMSManager:
    """
    SMS服务统一管理器
    使用示例:
    manager = SMSManager(provider_type=ProviderType.FIVE_SIM, api_key="abc...")
    order = await manager.rent_number("russia", "google")
    """
    
    def __init__(self, provider_type: ProviderType, api_key: str):
        self.provider_type = provider_type
        self.api_key = api_key
        self.provider: BaseSMSProvider = self._get_provider()
        logger.info(f"SMSManager initialized with {provider_type.value}")

    def _get_provider(self) -> BaseSMSProvider:
        if self.provider_type == ProviderType.SMS_MAN:
            return SMSManProvider(self.api_key)
        elif self.provider_type == ProviderType.FIVE_SIM:
            return FiveSimProvider(self.api_key)
        elif self.provider_type == ProviderType.VAK_SMS:
            return VakSMSProvider(self.api_key)
        else:
            raise ValueError("Unsupported provider type")

    async def get_balance(self) -> float:
        return await self.provider.get_balance()

    async def rent_number(self, country: str, service: str, duration: int = 4) -> SMSOrder:
        """租用号码"""
        return await self.provider.rent_number(country, service, duration)

    async def wait_for_code(self, order: SMSOrder, timeout_seconds: int = 300, check_interval: int = 5) -> SMSOrder:
        """
        轮询等待验证码
        :param order: 订单对象
        :param timeout_seconds: 最大等待时间
        :param check_interval: 检查间隔
        :return: 更新后的订单对象 (包含 code)
        """
        start_time = datetime.now()
        logger.info(f"Waiting for SMS code for order {order.order_id} ({order.phone_number})...")
        
        while (datetime.now() - start_time).total_seconds() < timeout_seconds:
            order = await self.provider.check_sms(order)
            
            if order.status == RentStatus.RECEIVED or order.sms_code:
                logger.info(f"SMS Received: {order.sms_code}")
                return order
            
            await asyncio.sleep(check_interval)
            
        logger.warning(f"Timeout waiting for SMS for order {order.order_id}")
        order.status = RentStatus.TIMEOUT
        return order

# --- 测试代码 ---
if __name__ == "__main__":
    # 简单的运行测试
    async def main():
        print("This module is designed to be imported. Please initialize SMSManager with a valid API key.")
        # example:
        # manager = SMSManager(ProviderType.VAK_SMS, "your_key")
        # print(await manager.get_balance())
    
    asyncio.run(main())
