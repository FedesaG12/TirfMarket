import React, { useState } from 'react';
import { X, CheckCircle, Loader2 } from 'lucide-react';

interface MpesaModalProps {
  isOpen: boolean;
  onClose: () => void;
  amount: number;
  dealTitle: string;
}

export default function MpesaModal({ isOpen, onClose, amount, dealTitle }: MpesaModalProps) {
  const [phoneNumber, setPhoneNumber] = useState('');
  const [status, setStatus] = useState<'idle' | 'loading' | 'success' | 'error'>('idle');

  if (!isOpen) return null;

  const handlePayment = (e: React.FormEvent) => {
    e.preventDefault();
    if (!phoneNumber) return;
    
    setStatus('loading');
    
    // Simulate M-Pesa STK Push
    setTimeout(() => {
      setStatus('success');
    }, 3000);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-md overflow-hidden relative">
        <button 
          onClick={onClose}
          className="absolute top-4 right-4 p-1 rounded-full hover:bg-gray-100 transition-colors"
        >
          <X className="w-5 h-5 text-gray-500" />
        </button>

        <div className="p-6">
          <div className="flex justify-center mb-6">
            <div className="w-24 h-12 bg-green-600 rounded-md flex items-center justify-center text-white font-bold text-xl tracking-wider">
              M-PESA
            </div>
          </div>
          
          <h2 className="text-xl font-bold text-center text-gray-900 mb-2">Pay with M-Pesa Safaricom</h2>
          <p className="text-center text-gray-500 text-sm mb-6">
            Complete your purchase for <span className="font-semibold text-gray-700">{dealTitle}</span>
          </p>

          <div className="bg-gray-50 rounded-xl p-4 mb-6 flex justify-between items-center border border-gray-100">
            <span className="text-gray-600">Total Amount</span>
            <span className="text-xl font-bold text-gray-900">ETB {amount.toLocaleString()}</span>
          </div>

          {status === 'idle' || status === 'error' ? (
            <form onSubmit={handlePayment}>
              <div className="mb-4">
                <label className="block text-sm font-medium text-gray-700 mb-1">M-Pesa Phone Number</label>
                <div className="relative">
                  <span className="absolute inset-y-0 left-0 flex items-center pl-3 text-gray-500 font-medium">
                    +251
                  </span>
                  <input
                    type="tel"
                    placeholder="7XX XXX XXX or 9XX XXX XXX"
                    className="w-full pl-14 pr-4 py-3 border border-gray-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-green-500 transition-shadow"
                    value={phoneNumber}
                    onChange={(e) => setPhoneNumber(e.target.value.replace(/\D/g, '').slice(0, 9))}
                    required
                  />
                </div>
                {status === 'error' && (
                  <p className="text-red-500 text-xs mt-2">Payment failed. Please try again.</p>
                )}
              </div>

              <button
                type="submit"
                className="w-full bg-green-600 hover:bg-green-700 text-white font-bold py-3 px-4 rounded-xl transition-colors shadow-md flex items-center justify-center"
              >
                Send Payment Request
              </button>
            </form>
          ) : status === 'loading' ? (
            <div className="text-center py-8">
              <Loader2 className="w-12 h-12 text-green-600 animate-spin mx-auto mb-4" />
              <h3 className="font-bold text-gray-900 mb-2">Awaiting Confirmation</h3>
              <p className="text-sm text-gray-500">
                Please check your phone and enter your M-Pesa PIN to complete the payment.
              </p>
            </div>
          ) : (
            <div className="text-center py-8">
              <div className="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-4">
                <CheckCircle className="w-10 h-10 text-green-600" />
              </div>
              <h3 className="font-bold text-green-700 text-xl mb-2">Payment Successful!</h3>
              <p className="text-sm text-gray-500 mb-6">
                Your deal voucher has been sent to your email and phone.
              </p>
              <button
                onClick={onClose}
                className="w-full bg-gray-900 hover:bg-black text-white font-bold py-3 px-4 rounded-xl transition-colors"
              >
                View Voucher
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
