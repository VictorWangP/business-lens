import uuid
from datetime import datetime, date
from sqlalchemy import String, Float, Integer, Date, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

class SalesOrder(Base):
    __tablename__ = "sales_orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    order_no: Mapped[str] = mapped_column(String(50), nullable=False)
    customer_name: Mapped[str] = mapped_column(String(100), nullable=False)
    product_name: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)      # 电子产品, 办公设备, 软件服务, 日用品
    region: Mapped[str] = mapped_column(String(50), nullable=False)        # 华东区, 华南区, 华北区, 西南区
    amount: Mapped[float] = mapped_column(Float, nullable=False)          # 销售金额
    quantity: Mapped[int] = mapped_column(Integer, default=1)              # 数量
    order_date: Mapped[date] = mapped_column(Date, default=date.today)     # 下单日期
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
