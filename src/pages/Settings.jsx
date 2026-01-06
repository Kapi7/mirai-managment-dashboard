import React, { useState } from "react";
import { base44 } from "@/api/base44Client";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Settings as SettingsIcon, TestTube, CheckCircle, XCircle, Loader2 } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";

export default function Settings() {
  const [testing, setTesting] = useState(false);
  const [results, setResults] = useState(null);

  const runTests = async () => {
    setTesting(true);
    try {
      const response = await base44.functions.invoke('testAPIs', {});
      setResults(response.data);
    } catch (err) {
      setResults({ error: err.message });
    } finally {
      setTesting(false);
    }
  };

  const StatusBadge = ({ success }) => {
    return success ? (
      <Badge className="bg-green-100 text-green-800 gap-1">
        <CheckCircle className="w-3 h-3" />
        Working
      </Badge>
    ) : (
      <Badge variant="destructive" className="gap-1">
        <XCircle className="w-3 h-3" />
        Failed
      </Badge>
    );
  };

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-slate-900">Settings</h1>
        <p className="text-slate-500 mt-1">Configure integrations and test API connections</p>
      </div>

      <Card className="border-slate-200">
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              <TestTube className="w-5 h-5" />
              API Connection Tests
            </CardTitle>
            <Button
              onClick={runTests}
              disabled={testing}
              className="gap-2"
            >
              {testing ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Testing...
                </>
              ) : (
                <>
                  <TestTube className="w-4 h-4" />
                  Run Tests
                </>
              )}
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-6">
          {results && (
            <>
              {/* Google Ads Results */}
              <div className="space-y-3">
                <h3 className="font-semibold text-lg">Google Ads</h3>
                
                <div className="bg-slate-50 rounded-lg p-4 space-y-2">
                  <div className="text-sm">
                    <span className="font-medium">Credentials:</span>
                    <div className="ml-4 mt-2 space-y-1 text-xs">
                      <div>Client ID: {results.google_ads?.credentials_set?.client_id ? '✅ Set' : '❌ Missing'}</div>
                      <div>Client Secret: {results.google_ads?.credentials_set?.client_secret ? '✅ Set' : '❌ Missing'}</div>
                      <div>Refresh Token: {results.google_ads?.credentials_set?.refresh_token ? '✅ Set' : '❌ Missing'}</div>
                      <div>Developer Token: {results.google_ads?.credentials_set?.developer_token ? '✅ Set' : '❌ Missing'}</div>
                      <div>Customer ID: {results.google_ads?.customer_id_value || '❌ Not set'}</div>
                    </div>
                  </div>
                  
                  {results.google_ads?.oauth_test && (
                    <div className="pt-2 border-t border-slate-200">
                      <div className="flex items-center justify-between">
                        <span className="text-sm font-medium">OAuth Authentication:</span>
                        <StatusBadge success={results.google_ads.oauth_test.success} />
                      </div>
                      {!results.google_ads.oauth_test.success && (
                        <pre className="mt-2 text-xs bg-red-50 p-2 rounded text-red-900 overflow-auto">
                          {JSON.stringify(results.google_ads.oauth_test.error, null, 2)}
                        </pre>
                      )}
                    </div>
                  )}
                  
                  {results.google_ads?.api_test && (
                    <div className="pt-2 border-t border-slate-200">
                      <div className="flex items-center justify-between">
                        <span className="text-sm font-medium">API Access:</span>
                        <StatusBadge success={results.google_ads.api_test.success} />
                      </div>
                      {!results.google_ads.api_test.success && (
                        <pre className="mt-2 text-xs bg-red-50 p-2 rounded text-red-900 overflow-auto max-h-40">
                          {JSON.stringify(results.google_ads.api_test.error, null, 2)}
                        </pre>
                      )}
                    </div>
                  )}
                </div>
              </div>

              {/* Meta Ads Results */}
              <div className="space-y-3">
                <h3 className="font-semibold text-lg">Meta Ads</h3>
                
                <div className="bg-slate-50 rounded-lg p-4 space-y-2">
                  <div className="text-sm">
                    <span className="font-medium">Credentials:</span>
                    <div className="ml-4 mt-2 space-y-1 text-xs">
                      <div>Access Token: {results.meta_ads?.credentials_set?.access_token ? '✅ Set' : '❌ Missing'}</div>
                      <div>Account ID: {results.meta_ads?.account_id_value || '❌ Not set'}</div>
                    </div>
                  </div>
                  
                  {results.meta_ads?.api_test && (
                    <div className="pt-2 border-t border-slate-200">
                      <div className="flex items-center justify-between">
                        <span className="text-sm font-medium">Account Access:</span>
                        <StatusBadge success={results.meta_ads.api_test.success} />
                      </div>
                      {results.meta_ads.api_test.success ? (
                        <div className="mt-2 text-xs space-y-1">
                          <div>Account: {results.meta_ads.api_test.account?.name}</div>
                          <div>Currency: {results.meta_ads.api_test.account?.currency}</div>
                          <div>Timezone: {results.meta_ads.api_test.account?.timezone_name}</div>
                        </div>
                      ) : (
                        <pre className="mt-2 text-xs bg-red-50 p-2 rounded text-red-900 overflow-auto max-h-40">
                          {JSON.stringify(results.meta_ads.api_test.error, null, 2)}
                        </pre>
                      )}
                    </div>
                  )}
                  
                  {results.meta_ads?.insights_test && (
                    <div className="pt-2 border-t border-slate-200">
                      <div className="flex items-center justify-between">
                        <span className="text-sm font-medium">Insights API:</span>
                        <StatusBadge success={results.meta_ads.insights_test.success} />
                      </div>
                      {results.meta_ads.insights_test.success ? (
                        <div className="mt-2 text-xs">
                          Data rows: {results.meta_ads.insights_test.data?.data?.length || 0}
                        </div>
                      ) : (
                        <pre className="mt-2 text-xs bg-red-50 p-2 rounded text-red-900 overflow-auto max-h-40">
                          {JSON.stringify(results.meta_ads.insights_test.error, null, 2)}
                        </pre>
                      )}
                    </div>
                  )}
                </div>
              </div>

              {results.error && (
                <Alert variant="destructive">
                  <AlertDescription>{results.error}</AlertDescription>
                </Alert>
              )}
            </>
          )}
          
          {!results && (
            <p className="text-slate-600 text-center py-8">
              Click "Run Tests" to verify your API credentials and connections
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}