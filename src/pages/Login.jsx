import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Alert, AlertDescription } from '@/components/ui/alert';

// Google Client ID from environment
const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID || '';

export default function Login() {
  const { loginWithGoogle, isAuthenticated, loading, error } = useAuth();
  const navigate = useNavigate();
  const [googleLoaded, setGoogleLoaded] = useState(false);
  const [loginInProgress, setLoginInProgress] = useState(false);

  // Redirect if already logged in
  useEffect(() => {
    if (isAuthenticated && !loading) {
      navigate('/');
    }
  }, [isAuthenticated, loading, navigate]);

  // Load Google Sign-In script
  useEffect(() => {
    if (!GOOGLE_CLIENT_ID) {
      console.warn('Google Client ID not configured');
      return;
    }

    const script = document.createElement('script');
    script.src = 'https://accounts.google.com/gsi/client';
    script.async = true;
    script.defer = true;
    script.onload = () => {
      setGoogleLoaded(true);
      initializeGoogle();
    };
    document.body.appendChild(script);

    return () => {
      // Cleanup
      const existingScript = document.querySelector('script[src="https://accounts.google.com/gsi/client"]');
      if (existingScript) {
        existingScript.remove();
      }
    };
  }, []);

  const initializeGoogle = () => {
    if (!window.google || !GOOGLE_CLIENT_ID) return;

    window.google.accounts.id.initialize({
      client_id: GOOGLE_CLIENT_ID,
      callback: handleGoogleCallback,
      auto_select: false
    });

    // Render the button
    const buttonDiv = document.getElementById('google-signin-button');
    if (buttonDiv) {
      window.google.accounts.id.renderButton(buttonDiv, {
        theme: 'outline',
        size: 'large',
        width: 300,
        text: 'signin_with'
      });
    }
  };

  const handleGoogleCallback = async (response) => {
    if (response.credential) {
      setLoginInProgress(true);
      const result = await loginWithGoogle(response.credential);
      if (result.success) {
        navigate('/');
      }
      setLoginInProgress(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto"></div>
          <p className="mt-4 text-slate-600">Loading...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-50 to-slate-100">
      <Card className="w-[400px] shadow-lg">
        <CardHeader className="text-center">
          <div className="mx-auto mb-4 text-4xl">
            <span role="img" aria-label="mirror">Mirai</span>
          </div>
          <CardTitle className="text-2xl">Mirai Dashboard</CardTitle>
          <CardDescription>Sign in to access your dashboard</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {error && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          {!GOOGLE_CLIENT_ID ? (
            <Alert>
              <AlertDescription>
                Google Sign-In not configured. Set VITE_GOOGLE_CLIENT_ID environment variable.
              </AlertDescription>
            </Alert>
          ) : (
            <div className="flex flex-col items-center space-y-4">
              {loginInProgress ? (
                <div className="text-center">
                  <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mx-auto"></div>
                  <p className="mt-2 text-sm text-slate-600">Signing in...</p>
                </div>
              ) : (
                <>
                  <div id="google-signin-button"></div>
                  {!googleLoaded && (
                    <p className="text-sm text-slate-500">Loading Google Sign-In...</p>
                  )}
                </>
              )}
            </div>
          )}

          <div className="text-center text-xs text-slate-500 mt-6">
            <p>Only authorized users can access this dashboard.</p>
            <p>Contact your admin if you need access.</p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
