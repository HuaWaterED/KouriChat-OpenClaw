"""
清理工具模块
负责清理系统中的临时文件和缓存，包括:
- 清理screenshot文件夹
- 清理__pycache__文件夹
- 提供统一的清理接口
"""

import os
import shutil
import logging
import time

logger = logging.getLogger(__name__)

class CleanupUtils:
    def __init__(self, root_dir: str):
        self.root_dir = root_dir
        self.screenshot_dir = os.path.join(root_dir, "screenshot")

    def cleanup_screenshot(self):
        """清理screenshot文件夹"""
        try:
            if os.path.isdir(self.screenshot_dir):
                shutil.rmtree(self.screenshot_dir)
                logger.info(f"目录 {self.screenshot_dir} 已成功删除")
            else:
                logger.info(f"目录 {self.screenshot_dir} 不存在，无需删除")
        except Exception as e:
            logger.error(f"清理screenshot目录失败: {str(e)}")

    def cleanup_update_files(self):
        """清理更新残留文件和目录"""
        try:
            # 清理backup目录
            backup_dir = os.path.join(self.root_dir, "backup")
            if os.path.exists(backup_dir):
                try:
                    shutil.rmtree(backup_dir)
                    logger.info(f"已清理备份目录: {backup_dir}")
                except Exception as e:
                    logger.error(f"清理备份目录失败: {str(e)}")
                    # 尝试使用系统命令强制删除
                    try:
                        import subprocess
                        if os.name == 'nt':  # Windows
                            subprocess.run(['rd', '/s', '/q', backup_dir], shell=True)
                        else:  # Linux/Mac
                            subprocess.run(['rm', '-rf', backup_dir])
                    except Exception as e2:
                        logger.error(f"使用系统命令清理备份目录失败: {str(e2)}")
            
            # 清理KouriChat-Kourichat-Festival-Test目录
            test_dir = os.path.join(self.root_dir, "KouriChat-Kourichat-Festival-Test")
            if os.path.exists(test_dir):
                try:
                    shutil.rmtree(test_dir)
                    logger.info(f"已清理测试目录: {test_dir}")
                except Exception as e:
                    logger.error(f"清理测试目录失败: {str(e)}")
                    # 尝试使用系统命令强制删除
                    try:
                        import subprocess
                        if os.name == 'nt':  # Windows
                            subprocess.run(['rd', '/s', '/q', test_dir], shell=True)
                        else:  # Linux/Mac
                            subprocess.run(['rm', '-rf', test_dir])
                    except Exception as e2:
                        logger.error(f"使用系统命令清理测试目录失败: {str(e2)}")
        except Exception as e:
            logger.error(f"清理更新残留文件失败: {str(e)}")

    def cleanup_all(self):
        """执行所有清理操作"""
        try:
            # 清理pycache
            cleanup_pycache()
            # 清理screenshot文件夹
            self.cleanup_screenshot()
            # 清理更新残留文件
            self.cleanup_update_files()
            logger.info("所有清理操作完成")
        except Exception as e:
            logger.error(f"清理操作失败: {str(e)}")

def cleanup_pycache():
    """递归清理所有__pycache__文件夹"""
    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    for root, dirs, files in os.walk(root_dir):
        if '__pycache__' in dirs:
            pycache_path = os.path.join(root, '__pycache__')
            try:
                shutil.rmtree(pycache_path)
                logger.info(f"已清理: {pycache_path}")
            except Exception as e:
                logger.error(f"清理失败 {pycache_path}: {str(e)}") 