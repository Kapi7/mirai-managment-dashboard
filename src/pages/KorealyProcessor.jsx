import React, { useState, useEffect } from "react";
import { api } from "@/api/apiClient";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { Package, RefreshCw, Loader2, Mail, History, AlertCircle, CheckCircle2 } from "lucide-react";

export default function KorealyProcessor() {
    const [pendingEmails, setPendingEmails] = useState([]);
    const [allEmails, setAllEmails] = useState([]);
    const [gmailAccount, setGmailAccount] = useState(null);
    const [loading, setLoading] = useState(true);
    const [processing, setProcessing] = useState({});
    const [updatingAll, setUpdatingAll] = useState(false);
    const [message, setMessage] = useState(null);

    const fetchEmails = async () => {
        setLoading(true);
        setMessage(null);
        try {
            const data = await api.fetchKorealyEmails();

            setPendingEmails(data.pending || []);
            setAllEmails(data.all || []);
            setGmailAccount(data.gmailAccount);
        } catch (error) {
            console.error('Fetch emails error:', error);
            setMessage({ type: 'error', text: error.message || 'Failed to fetch emails' });
        } finally {
            setLoading(false);
        }
    };

    const addTracking = async (email) => {
        setProcessing(prev => ({ ...prev, [email.id]: true }));
        setMessage(null);

        try {
            await api.updateShopifyTracking(
                email.orderNumber,
                email.korealyTracking,
                email.carrier
            );

            setMessage({
                type: 'success',
                text: `✅ Tracking added for order #${email.orderNumber}`
            });

            // Remove from pending list locally instead of refetching
            setPendingEmails(prev => prev.filter(e => e.id !== email.id));

            // Move to all emails with shopify tracking
            setAllEmails(prev => prev.map(e =>
                e.id === email.id
                    ? { ...e, shopifyTracking: email.korealyTracking }
                    : e
            ));
        } catch (error) {
            console.error('Update tracking error:', error);
            setMessage({
                type: 'error',
                text: error.message || 'Failed to add tracking'
            });
        } finally {
            setProcessing(prev => ({ ...prev, [email.id]: false }));
        }
    };



    const updateAll = async () => {
        if (pendingEmails.length === 0) return;

        setUpdatingAll(true);
        setMessage(null);

        let successCount = 0;
        let failedCount = 0;
        const successfulIds = [];

        for (const email of pendingEmails) {
            try {
                await api.updateShopifyTracking(
                    email.orderNumber,
                    email.korealyTracking,
                    email.carrier
                );
                successCount++;
                successfulIds.push(email.id);
            } catch (error) {
                failedCount++;
                console.error(`Failed to update order #${email.orderNumber}:`, error);
            }
        }

        setMessage({
            type: failedCount === 0 ? 'success' : 'error',
            text: `✅ Updated ${successCount} orders${failedCount > 0 ? `, ${failedCount} failed` : ''}`
        });

        // Update state locally
        setPendingEmails(prev => prev.filter(e => !successfulIds.includes(e.id)));
        setAllEmails(prev => prev.map(e =>
            successfulIds.includes(e.id)
                ? { ...e, shopifyTracking: e.korealyTracking }
                : e
        ));

        setUpdatingAll(false);
    };

    useEffect(() => {
        fetchEmails();
    }, []);

    return (
        <div className="p-6 space-y-6">
            <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
                <div>
                    <h1 className="text-3xl font-bold text-slate-900">Korealy Tracking</h1>
                    <p className="text-slate-500 mt-1">Sync shipping emails from order@korealy with Shopify</p>
                    {gmailAccount && (
                        <p className="text-xs text-slate-400 mt-1">📧 Connected to: {gmailAccount}</p>
                    )}
                </div>
                <div className="flex gap-2">
                    {pendingEmails.length > 0 && (
                        <Button 
                            onClick={updateAll}
                            disabled={updatingAll || loading}
                            className="gap-2 bg-green-600 hover:bg-green-700"
                        >
                            {updatingAll ? (
                                <>
                                    <Loader2 className="w-4 h-4 animate-spin" />
                                    Updating All...
                                </>
                            ) : (
                                <>
                                    <Package className="w-4 h-4" />
                                    Update All ({pendingEmails.length})
                                </>
                            )}
                        </Button>
                    )}
                    <Button 
                        onClick={fetchEmails}
                        disabled={loading}
                        className="gap-2 bg-indigo-600 hover:bg-indigo-700"
                    >
                        {loading ? (
                            <Loader2 className="w-4 h-4 animate-spin" />
                        ) : (
                            <RefreshCw className="w-4 h-4" />
                        )}
                        Refresh
                    </Button>
                </div>
            </div>

            {message && (
                <Alert variant={message.type === 'error' ? 'destructive' : 'default'}>
                    <AlertDescription>{message.text}</AlertDescription>
                </Alert>
            )}

            <Card>
                <CardHeader>
                    <CardTitle className="flex items-center gap-2">
                        <Mail className="w-5 h-5" />
                        Pending Updates ({pendingEmails.length})
                    </CardTitle>
                </CardHeader>
                <CardContent>
                    {loading ? (
                        <div className="space-y-2">
                            {[...Array(3)].map((_, i) => (
                                <Skeleton key={i} className="h-12 w-full" />
                            ))}
                        </div>
                    ) : pendingEmails.length === 0 ? (
                        <div className="text-center py-12">
                            <CheckCircle2 className="w-12 h-12 text-green-500 mx-auto mb-3" />
                            <p className="text-slate-600 font-medium">All caught up!</p>
                            <p className="text-slate-500 text-sm mt-1">No pending Korealy shipments</p>
                        </div>
                    ) : (
                        <div className="overflow-x-auto">
                            <table className="w-full text-sm">
                                <thead>
                                    <tr className="border-b border-slate-200">
                                        <th className="text-left p-3 font-semibold text-slate-700">Order #</th>
                                        <th className="text-left p-3 font-semibold text-slate-700">Date</th>
                                        <th className="text-left p-3 font-semibold text-slate-700">Carrier</th>
                                        <th className="text-left p-3 font-semibold text-slate-700">Korealy Tracking</th>
                                        <th className="text-left p-3 font-semibold text-slate-700">Shopify Tracking</th>
                                        <th className="text-center p-3 font-semibold text-slate-700">Action</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {pendingEmails.map((email) => (
                                        <tr key={email.id} className="border-b border-slate-100 hover:bg-slate-50">
                                            <td className="p-3">
                                                <Badge variant="outline" className="font-mono">
                                                    #{email.orderNumber}
                                                </Badge>
                                            </td>
                                            <td className="p-3 text-slate-600">
                                                {new Date(email.date).toLocaleDateString('en-US', { 
                                                    month: 'short', 
                                                    day: 'numeric',
                                                    year: 'numeric'
                                                })}
                                            </td>
                                            <td className="p-3 text-slate-600 text-xs">
                                                {email.carrier || 'Australia Post'}
                                            </td>
                                            <td className="p-3 font-mono text-xs text-slate-700">
                                                {email.korealyTracking}
                                            </td>
                                            <td className="p-3 font-mono text-xs text-slate-400">
                                                —
                                            </td>
                                            <td className="p-3 text-center">
                                                <Button
                                                    onClick={() => addTracking(email)}
                                                    disabled={processing[email.id]}
                                                    size="sm"
                                                    className="gap-2 bg-green-600 hover:bg-green-700"
                                                >
                                                    {processing[email.id] ? (
                                                        <>
                                                            <Loader2 className="w-3 h-3 animate-spin" />
                                                            Updating...
                                                        </>
                                                    ) : (
                                                        <>
                                                            <Package className="w-3 h-3" />
                                                            Update
                                                        </>
                                                    )}
                                                </Button>
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </CardContent>
            </Card>

            <Card>
                <CardHeader>
                    <CardTitle className="flex items-center gap-2">
                        <History className="w-5 h-5" />
                        All Shipments ({allEmails.length})
                    </CardTitle>
                </CardHeader>
                <CardContent>
                    {loading ? (
                        <div className="space-y-2">
                            {[...Array(5)].map((_, i) => (
                                <Skeleton key={i} className="h-12 w-full" />
                            ))}
                        </div>
                    ) : allEmails.length === 0 ? (
                        <div className="text-center py-8">
                            <p className="text-slate-500">No Korealy emails found</p>
                            {gmailAccount && (
                                <p className="text-xs text-slate-400 mt-2">Searching in: {gmailAccount}</p>
                            )}
                        </div>
                    ) : (
                        <div className="overflow-x-auto">
                            <table className="w-full text-sm">
                                <thead>
                                    <tr className="border-b border-slate-200">
                                        <th className="text-left p-3 font-semibold text-slate-700">Order #</th>
                                        <th className="text-left p-3 font-semibold text-slate-700">Date</th>
                                        <th className="text-left p-3 font-semibold text-slate-700">Carrier</th>
                                        <th className="text-left p-3 font-semibold text-slate-700">Korealy Tracking</th>
                                        <th className="text-left p-3 font-semibold text-slate-700">Shopify Tracking</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {allEmails.map((email) => (
                                        <tr key={email.id} className="border-b border-slate-100 hover:bg-slate-50">
                                            <td className="p-3">
                                                <Badge variant="outline" className="font-mono">
                                                    #{email.orderNumber}
                                                </Badge>
                                            </td>
                                            <td className="p-3 text-slate-600">
                                                {new Date(email.date).toLocaleDateString('en-US', { 
                                                    month: 'short', 
                                                    day: 'numeric',
                                                    year: 'numeric'
                                                })}
                                            </td>
                                            <td className="p-3 text-slate-600 text-xs">
                                                {email.carrier || 'Australia Post'}
                                            </td>
                                            <td className="p-3 font-mono text-xs text-slate-700">
                                                {email.korealyTracking}
                                            </td>
                                            <td className="p-3 font-mono text-xs">
                                                {email.shopifyTracking ? (
                                                    <span className="text-green-700">{email.shopifyTracking}</span>
                                                ) : (
                                                    <span className="text-slate-400">—</span>
                                                )}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </CardContent>
            </Card>
        </div>
    );
}