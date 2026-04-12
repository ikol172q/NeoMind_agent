import logging
import logging.handlers
import sys
import os
from datetime import datetime
from pathlib import Path

def setup_logging(
    log_dir="logs",
    log_file="app.log",
    console_level=logging.INFO,
    file_level=logging.DEBUG,
    max_bytes=10 * 1024 * 1024,  # 10 MB
    backup_count=5,
    enable_console=True,
    enable_file=True
):
    """
    设置Python日志系统，支持控制台输出和文件轮转
    
    Args:
        log_dir: 日志目录
        log_file: 日志文件名
        console_level: 控制台日志级别
        file_level: 文件日志级别
        max_bytes: 每个日志文件最大字节数
        backup_count: 保留的备份文件数量
        enable_console: 是否启用控制台日志
        enable_file: 是否启用文件日志
    """
    # 确保日志目录存在
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    
    # 创建logger
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)  # 设置为最低级别，让handler控制
    
    # 清除已有的handler，避免重复
    logger.handlers.clear()
    
    # 通用格式
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # 控制台handler
    if enable_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(console_level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    
    # 文件handler（支持轮转）
    if enable_file:
        log_path = Path(log_dir) / log_file
        file_handler = logging.handlers.RotatingFileHandler(
            filename=str(log_path),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8'
        )
        file_handler.setLevel(file_level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    return logger

def get_logger(name=__name__):
    """获取指定名称的logger实例"""
    return logging.getLogger(name)

# 使用示例
if __name__ == "__main__":
    # 设置日志（默认配置）
    setup_logging()
    
    # 获取logger
    logger = get_logger(__name__)
    
    # 测试日志输出
    logger.debug("这是一个debug级别的消息")
    logger.info("这是一个info级别的消息")
    logger.warning("这是一个warning级别的消息")
    logger.error("这是一个error级别的消息")
    
    # 创建大量日志测试轮转功能
    for i in range(100):
        logger.info(f"测试日志轮转 - 消息 {i}")
    
    print("日志设置完成，检查 logs/app.log 文件")

# 高级配置示例
def setup_advanced_logging():
    """高级日志配置：不同日志级别输出到不同文件"""
    
    # 主日志配置
    main_logger = setup_logging(
        log_dir="logs",
        log_file="app_main.log",
        console_level=logging.INFO,
        file_level=logging.DEBUG,
        max_bytes=5 * 1024 * 1024,  # 5 MB
        backup_count=10
    )
    
    # 单独的错误日志文件
    error_handler = logging.handlers.RotatingFileHandler(
        filename="logs/error.log",
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding='utf-8'
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(logging.Formatter(
        '%(asctime)s - ERROR - %(message)s'
    ))
    main_logger.addHandler(error_handler)
    
    # 时间轮转（每天一个文件）
    time_handler = logging.handlers.TimedRotatingFileHandler(
        filename="logs/daily.log",
        when='midnight',
        interval=1,
        backupCount=7,
        encoding='utf-8'
    )
    time_handler.setLevel(logging.INFO)
    time_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s'
    ))
    main_logger.addHandler(time_handler)
    
    return main_logger
