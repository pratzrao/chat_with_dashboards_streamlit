import subprocess
import time
import logging
import signal
import os
import tempfile
import streamlit as st
from typing import Optional

logger = logging.getLogger(__name__)

class SSHTunnel:
    def __init__(self, ssh_host: str, ssh_port: int, ssh_user: str, ssh_key_path: str,
                 remote_host: str, remote_port: int, local_port: int = 15432):
        self.ssh_host = ssh_host
        self.ssh_port = ssh_port
        self.ssh_user = ssh_user
        self.ssh_key_path = ssh_key_path
        self.remote_host = remote_host
        self.remote_port = remote_port
        self.local_port = local_port
        self.process: Optional[subprocess.Popen] = None
    
    def start(self) -> bool:
        """Start SSH tunnel"""
        if self.is_running():
            logger.info("SSH tunnel already running")
            return True
        
        cmd = [
            "ssh",
            "-N",  # Don't execute remote commands
            "-L", f"{self.local_port}:{self.remote_host}:{self.remote_port}",
            "-p", str(self.ssh_port),
            "-i", self.ssh_key_path,
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "ServerAliveInterval=30",
            "-o", "ServerAliveCountMax=3",
            f"{self.ssh_user}@{self.ssh_host}"
        ]
        
        try:
            logger.info(f"Starting SSH tunnel: localhost:{self.local_port} -> {self.remote_host}:{self.remote_port}")
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                preexec_fn=os.setsid  # Create new process group
            )
            
            # Give tunnel time to establish
            time.sleep(2)
            
            if self.process.poll() is None:
                logger.info("SSH tunnel started successfully")
                return True
            else:
                stderr = self.process.stderr.read().decode() if self.process.stderr else ""
                logger.error(f"SSH tunnel failed to start: {stderr}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to start SSH tunnel: {e}")
            return False
    
    def stop(self):
        """Stop SSH tunnel"""
        if self.process:
            try:
                # Kill the entire process group to ensure cleanup
                os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
                self.process.wait(timeout=5)
                logger.info("SSH tunnel stopped")
            except subprocess.TimeoutExpired:
                os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
                logger.warning("SSH tunnel force killed")
            except Exception as e:
                logger.error(f"Error stopping SSH tunnel: {e}")
            finally:
                self.process = None
    
    def is_running(self) -> bool:
        """Check if tunnel is running"""
        if self.process is None:
            return False
        return self.process.poll() is None
    
    def __enter__(self):
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()

def get_ssh_key_path() -> str:
    """Get SSH key path, creating temp file from secrets if needed"""
    
    def get_config_value(key: str, default=None):
        """Get config value from Streamlit secrets first, then environment"""
        try:
            # Try Streamlit secrets first
            if hasattr(st, 'secrets') and key in st.secrets:
                return st.secrets[key]
        except Exception:
            # Fallback to environment variable if secrets not available
            pass
        return os.getenv(key, default)
    
    # Check if SSH_PRIVATE_KEY is provided in secrets (for cloud deployment)
    ssh_private_key = get_config_value("SSH_PRIVATE_KEY")
    if ssh_private_key:
        # Create temporary key file
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.pem') as f:
            # Write the private key content - handle both formats
            key_content = ssh_private_key.strip()
            
            # Ensure key starts with proper header
            if not key_content.startswith('-----BEGIN'):
                # If it's base64 encoded, decode it
                try:
                    import base64
                    key_content = base64.b64decode(key_content).decode('utf-8')
                except:
                    pass
            
            f.write(key_content)
            if not key_content.endswith('\n'):
                f.write('\n')
            temp_key_path = f.name
        
        # Set proper permissions for SSH key
        os.chmod(temp_key_path, 0o600)
        logger.info(f"Created temporary SSH key file for cloud deployment: {temp_key_path}")
        return temp_key_path
    
    # Fallback to local key file path (for development)
    ssh_key_path = get_config_value("SSH_KEY_PATH", "~/.ssh/id_rsa")
    return os.path.expanduser(ssh_key_path)

def create_tunnel() -> SSHTunnel:
    """Create SSH tunnel with configuration from environment or secrets"""
    
    def get_config_value(key: str, default=None):
        """Get config value from Streamlit secrets first, then environment"""
        try:
            # Try Streamlit secrets first
            if hasattr(st, 'secrets') and key in st.secrets:
                return st.secrets[key]
        except Exception:
            # Fallback to environment variable if secrets not available
            pass
        return os.getenv(key, default)
    
    ssh_key_path = get_ssh_key_path()
    ssh_host = get_config_value("SSH_HOST", "13.204.16.60")
    ssh_port = int(get_config_value("SSH_PORT", "22"))
    ssh_user = get_config_value("SSH_USER", "tunneluser")
    remote_host = get_config_value("REMOTE_DB_HOST", "bhumi-dalgo-db.chbulp4kqzjb.ap-south-1.rds.amazonaws.com")
    remote_port = int(get_config_value("REMOTE_DB_PORT", "5432"))
    local_port = int(get_config_value("LOCAL_TUNNEL_PORT", "15432"))

    return SSHTunnel(
        ssh_host=ssh_host,
        ssh_port=ssh_port,
        ssh_user=ssh_user, 
        ssh_key_path=ssh_key_path,
        remote_host=remote_host,
        remote_port=remote_port,
        local_port=local_port
    )
