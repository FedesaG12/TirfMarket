'use client';

import React, { useEffect, useState } from 'react';
import { supabase } from '@/lib/supabase';
import { Store, PlusCircle, Clock, CheckCircle2, XCircle, Loader2, Image as ImageIcon } from 'lucide-react';
import Link from 'next/link';
import Image from 'next/image';

interface Deal {
  id: string;
  title: string;
  category: string;
  original_price: number;
  discounted_price: number;
  status: string;
  image_url: string;
  created_at: string;
}

export default function SellerDashboard() {
  const [deals, setDeals] = useState<Deal[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  
  // Form State
  const [title, setTitle] = useState('');
  const [merchantName, setMerchantName] = useState('');
  const [category, setCategory] = useState('Food & Drink');
  const [originalPrice, setOriginalPrice] = useState('');
  const [discountedPrice, setDiscountedPrice] = useState('');
  
  // New Groupon-like fields
  const [description, setDescription] = useState('');
  const [location, setLocation] = useState('');
  const [finePrint, setFinePrint] = useState('');
  const [highlights, setHighlights] = useState('');
  
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [userId, setUserId] = useState('');

  useEffect(() => {
    checkSellerAndFetchDeals();
  }, []);

  const checkSellerAndFetchDeals = async () => {
    try {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) {
        setError("You must be logged in to view this page.");
        setLoading(false);
        return;
      }
      setUserId(user.id);

      const { data: profile } = await supabase
        .from('profiles')
        .select('account_type, full_name')
        .eq('id', user.id)
        .single();
        
      if (!profile || profile.account_type !== 'seller') {
        setError("Access Denied. You must be a registered Seller to post deals.");
        setLoading(false);
        return;
      }
      
      if (profile.full_name && !merchantName) {
        setMerchantName(profile.full_name);
      }

      fetchDeals(user.id);
    } catch (err: any) {
      setError(err.message);
      setLoading(false);
    }
  };

  const fetchDeals = async (uid: string) => {
    const { data, error } = await supabase
      .from('deals')
      .select('*')
      .eq('seller_id', uid)
      .order('created_at', { ascending: false });

    if (!error && data) {
      setDeals(data);
    }
    setLoading(false);
  };

  const handleImageUpload = async (file: File) => {
    const fileExt = file.name.split('.').pop();
    const fileName = `${Math.random()}.${fileExt}`;
    const { error: uploadError } = await supabase.storage
      .from('deal-images')
      .upload(fileName, file);

    if (uploadError) {
      console.error('Upload error:', uploadError);
      return null;
    }
    const { data: publicUrlData } = supabase.storage
      .from('deal-images')
      .getPublicUrl(fileName);
    return publicUrlData.publicUrl;
  };

  const handleSubmitDeal = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    
    let uploadedImageUrl = 'https://images.unsplash.com/photo-1556742049-0cfed4f6a45d?auto=format&fit=crop&q=80&w=800';
    if (imageFile) {
      const url = await handleImageUpload(imageFile);
      if (url) uploadedImageUrl = url;
    }
    
    const newDeal = {
      seller_id: userId,
      title,
      description,
      location,
      fine_print: finePrint,
      highlights,
      merchant_name: merchantName,
      category,
      original_price: parseFloat(originalPrice),
      discounted_price: parseFloat(discountedPrice),
      image_url: uploadedImageUrl,
      status: 'pending' // requires admin approval
    };

    const { error } = await supabase.from('deals').insert([newDeal]);

    if (error) {
      alert("Error posting deal: " + error.message);
    } else {
      alert("Deal submitted successfully! It is now pending Admin approval.");
      setTitle('');
      setDescription('');
      setLocation('');
      setFinePrint('');
      setHighlights('');
      setOriginalPrice('');
      setDiscountedPrice('');
      setImageFile(null);
      fetchDeals(userId); // refresh list
    }
    setIsSubmitting(false);
  };

  if (loading) {
    return <div className="min-h-screen flex items-center justify-center bg-gray-50"><Loader2 className="w-8 h-8 animate-spin text-green-600" /></div>;
  }

  if (error) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center bg-gray-50 p-4">
        <Store className="w-16 h-16 text-red-500 mb-4" />
        <h1 className="text-2xl font-bold text-gray-900 mb-2">Access Denied</h1>
        <p className="text-gray-600 mb-6 text-center">{error}</p>
        <Link href="/" className="bg-green-600 text-white px-6 py-2 rounded-lg font-medium hover:bg-green-700">
          Return to Homepage
        </Link>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 pb-12">
      <header className="bg-white border-b py-4 shadow-sm sticky top-0 z-10">
        <div className="container mx-auto px-4 flex justify-between items-center">
          <div className="flex items-center gap-2">
            <Store className="w-6 h-6 text-green-600" />
            <h1 className="text-xl font-bold text-gray-900">Seller Dashboard</h1>
          </div>
          <Link href="/" className="text-sm font-medium text-green-600 hover:underline">
            Back to Home
          </Link>
        </div>
      </header>

      <main className="container mx-auto px-4 mt-8 grid md:grid-cols-3 gap-8">
        
        {/* Post New Deal Form */}
        <div className="md:col-span-1">
          <div className="bg-white p-6 rounded-2xl shadow-sm border border-gray-100">
            <h2 className="text-lg font-bold text-gray-900 mb-4 flex items-center gap-2">
              <PlusCircle className="w-5 h-5 text-green-600" /> Post a New Deal
            </h2>
            <form onSubmit={handleSubmitDeal} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Business / Merchant Name</label>
                <input required type="text" value={merchantName} onChange={e=>setMerchantName(e.target.value)} className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-green-500" placeholder="e.g. Yod Abyssinia" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Deal Title</label>
                <input required type="text" value={title} onChange={e=>setTitle(e.target.value)} className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-green-500" placeholder="e.g. 50% off Buffet" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Category</label>
                <select value={category} onChange={e=>setCategory(e.target.value)} className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-green-500">
                  <option>Food & Drink</option>
                  <option>Coffee & Cafe</option>
                  <option>Spa & Wellness</option>
                  <option>Hotels & Travel</option>
                  <option>Electronics</option>
                  <option>Auto Services</option>
                </select>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Original Price (ETB)</label>
                  <input required type="number" min="0" value={originalPrice} onChange={e=>setOriginalPrice(e.target.value)} className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-green-500" />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Discount Price (ETB)</label>
                  <input required type="number" min="0" value={discountedPrice} onChange={e=>setDiscountedPrice(e.target.value)} className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-green-500" />
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Location</label>
                <input required type="text" value={location} onChange={e=>setLocation(e.target.value)} className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-green-500" placeholder="e.g. Bole, Addis Ababa" />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">About This Deal</label>
                <textarea rows={3} required value={description} onChange={e=>setDescription(e.target.value)} className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-green-500" placeholder="Describe the offer..."></textarea>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Highlights (Optional)</label>
                <textarea rows={2} value={highlights} onChange={e=>setHighlights(e.target.value)} className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-green-500" placeholder="Key benefits..."></textarea>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">The Fine Print (Optional)</label>
                <textarea rows={2} value={finePrint} onChange={e=>setFinePrint(e.target.value)} className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-green-500" placeholder="Valid only on weekdays, etc."></textarea>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Upload Photo</label>
                <div className="mt-1 flex justify-center px-6 pt-5 pb-6 border-2 border-gray-300 border-dashed rounded-lg">
                  <div className="space-y-1 text-center">
                    <ImageIcon className="mx-auto h-12 w-12 text-gray-400" />
                    <div className="flex text-sm text-gray-600 justify-center">
                      <label className="relative cursor-pointer bg-white rounded-md font-medium text-green-600 hover:text-green-500">
                        <span>Upload a file</span>
                        <input type="file" accept="image/*" className="sr-only" onChange={(e) => e.target.files && setImageFile(e.target.files[0])} />
                      </label>
                    </div>
                    <p className="text-xs text-gray-500">{imageFile ? imageFile.name : 'PNG, JPG, GIF up to 5MB'}</p>
                  </div>
                </div>
              </div>

              <button disabled={isSubmitting} type="submit" className="w-full bg-green-600 hover:bg-green-700 text-white font-bold py-3 rounded-xl transition-colors flex justify-center items-center">
                {isSubmitting ? <Loader2 className="w-5 h-5 animate-spin" /> : 'Submit for Approval'}
              </button>
            </form>
          </div>
        </div>

        {/* My Deals List */}
        <div className="md:col-span-2">
          <div className="bg-white rounded-2xl shadow-sm border border-gray-100 overflow-hidden">
            <div className="p-6 border-b border-gray-100">
              <h2 className="text-lg font-bold text-gray-900">My Submitted Deals</h2>
            </div>
            <div className="divide-y divide-gray-100">
              {deals.length === 0 ? (
                <div className="p-8 text-center text-gray-500">You haven't submitted any deals yet.</div>
              ) : (
                deals.map(deal => (
                  <div key={deal.id} className="p-6 flex gap-4 items-center">
                    <div className="relative w-20 h-20 rounded-lg overflow-hidden bg-gray-100 flex-shrink-0">
                      {deal.image_url && <Image src={deal.image_url} alt={deal.title} fill className="object-cover" />}
                    </div>
                    <div className="flex-1">
                      <h3 className="font-bold text-gray-900">{deal.title}</h3>
                      <p className="text-sm text-gray-500">{deal.category} • ETB {deal.discounted_price}</p>
                    </div>
                    <div>
                      {deal.status === 'pending' && <span className="inline-flex items-center gap-1 text-yellow-600 bg-yellow-50 px-3 py-1 rounded-full text-sm font-medium"><Clock className="w-4 h-4" /> Pending</span>}
                      {deal.status === 'approved' && <span className="inline-flex items-center gap-1 text-green-600 bg-green-50 px-3 py-1 rounded-full text-sm font-medium"><CheckCircle2 className="w-4 h-4" /> Approved</span>}
                      {deal.status === 'rejected' && <span className="inline-flex items-center gap-1 text-red-600 bg-red-50 px-3 py-1 rounded-full text-sm font-medium"><XCircle className="w-4 h-4" /> Rejected</span>}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>

      </main>
    </div>
  );
}
