import React from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Settings as SettingsIcon, Package, Mail } from "lucide-react";

export default function Settings() {

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-slate-900">Integrations</h1>
        <p className="text-slate-500 mt-1">Connected services and API integrations</p>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        {/* Gmail Integration */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Mail className="w-5 h-5" />
              Gmail API
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="text-sm text-slate-600">
              <div className="font-medium mb-2">Status: <span className="text-green-600">Connected</span></div>
              <div className="space-y-1 text-xs">
                <div>• Reads emails from order@korealy</div>
                <div>• OAuth2 authentication</div>
                <div>• Configured via .env</div>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Shopify Integration */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Package className="w-5 h-5" />
              Shopify API
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="text-sm text-slate-600">
              <div className="font-medium mb-2">Status: <span className="text-green-600">Connected</span></div>
              <div className="space-y-1 text-xs">
                <div>• Updates order fulfillments</div>
                <div>• Adds tracking numbers</div>
                <div>• Admin API access</div>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <SettingsIcon className="w-5 h-5" />
            Configuration
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-slate-600">
            All integrations are configured via environment variables in your <code className="bg-slate-100 px-2 py-1 rounded text-xs">.env</code> file.
          </p>
          <div className="text-xs text-slate-500 space-y-1 bg-slate-50 p-4 rounded">
            <div><strong>Gmail:</strong> GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN</div>
            <div><strong>Shopify:</strong> SHOPIFY_STORE, SHOPIFY_ACCESS_TOKEN</div>
          </div>
          <p className="text-xs text-slate-500">
            See <code className="bg-slate-100 px-2 py-1 rounded">GMAIL_SETUP.md</code> for Gmail OAuth setup instructions.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}