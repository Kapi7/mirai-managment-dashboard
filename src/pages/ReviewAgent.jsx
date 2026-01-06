import React from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { MessageSquare } from "lucide-react";

export default function ReviewAgent() {
  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-slate-900">Review Agent</h1>
        <p className="text-slate-500 mt-1">AI-powered customer review management</p>
      </div>

      <Card className="border-slate-200">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <MessageSquare className="w-5 h-5" />
            Coming Soon
            <Badge variant="secondary" className="ml-auto bg-amber-100 text-amber-700">Soon</Badge>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-slate-600">
            AI agent for automated review monitoring, response generation, and sentiment analysis.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}