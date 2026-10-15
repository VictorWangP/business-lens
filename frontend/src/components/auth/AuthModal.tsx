import React, { useState } from 'react';
import { Lock, User, Mail, Bot, AlertCircle } from 'lucide-react';
import { Alert, AlertDescription } from '../ui/alert';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { Label } from '../ui/label';
import { Dialog, DialogContent, DialogTitle, DialogDescription } from '../ui/dialog';
import { useAuth } from '../../context/AuthContext';

export const AuthModal: React.FC = () => {
  const { user, login, register } = useAuth();
  const [isRegister, setIsRegister] = useState(false);
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('password123');
  const [email, setEmail] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  if (user) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      if (isRegister) {
        await register(username, password, email || undefined);
      } else {
        await login(username, password);
      }
    } catch (err: any) {
      setError(err.message || '操作失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open>
      <DialogContent className="max-w-md [&>button]:hidden" onEscapeKeyDown={e => e.preventDefault()} onPointerDownOutside={e => e.preventDefault()}>
        <div className="text-center space-y-2">
          <div className="w-12 h-12 rounded-2xl bg-primary text-primary-foreground flex items-center justify-center mx-auto shadow-md shadow-primary/20">
            <Bot className="w-6 h-6" />
          </div>
          <DialogTitle className="text-xl font-bold">
            {isRegister ? '创建新账号' : '登录经管之星 BusinessLens'}
          </DialogTitle>
          <DialogDescription>
            已开启端到端租户多维数据隔离保护
          </DialogDescription>
        </div>

        {error && (
          <Alert variant="destructive"><AlertCircle className="h-4 w-4" /><AlertDescription>{error}</AlertDescription></Alert>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <Label htmlFor="auth-username">
              用户名
            </Label>
            <div className="relative mt-1.5">
              <User className="w-4 h-4 text-muted-foreground absolute left-3.5 top-2.5" />
              <Input
                id="auth-username"
                type="text"
                required
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="请输入用户名"
                className="pl-10"
              />
            </div>
          </div>

          {isRegister && (
            <div>
              <Label htmlFor="auth-email">
                电子邮箱 (可选)
              </Label>
              <div className="relative mt-1.5">
                <Mail className="w-4 h-4 text-muted-foreground absolute left-3.5 top-2.5" />
                <Input
                  id="auth-email" type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="your@email.com"
                  className="pl-10"
                />
              </div>
            </div>
          )}

          <div>
            <Label htmlFor="auth-password">
              登录密码
            </Label>
            <div className="relative mt-1.5">
              <Lock className="w-4 h-4 text-muted-foreground absolute left-3.5 top-2.5" />
              <Input
                id="auth-password"
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                className="pl-10"
              />
            </div>
          </div>

          <Button
            type="submit"
            disabled={loading}
            className="w-full"
          >
            {loading ? '处理中...' : isRegister ? '立即注册并进入' : '立即登录'}
          </Button>
        </form>

        <div className="text-center pt-2">
          <Button
            type="button"
            variant="link"
            onClick={() => {
              setIsRegister(!isRegister);
              setError(null);
            }}
            className="text-xs"
          >
            {isRegister ? '已有账号？返回直接登录' : '没有账号？点击注册新用户'}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
};
