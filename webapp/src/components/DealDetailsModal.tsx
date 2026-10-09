"use client";
import React, { useState, useEffect } from 'react';
import { X, MapPin, Star, Upload, Loader2, Image as ImageIcon } from 'lucide-react';
import Image from 'next/image';
import { supabase } from '@/lib/supabase';

interface DealDetailsModalProps {
  deal: any;
  isOpen: boolean;
  onClose: () => void;
  onBuy: () => void;
}

export default function DealDetailsModal({ deal, isOpen, onClose, onBuy }: DealDetailsModalProps) {
  const [reviews, setReviews] = useState<any[]>([]);
  const [loadingReviews, setLoadingReviews] = useState(true);
  
  // Review form state
  const [rating, setRating] = useState(5);
  const [comment, setComment] = useState('');
  const [reviewImage, setReviewImage] = useState<File | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [user, setUser] = useState<any>(null);

  useEffect(() => {
    if (!isOpen || !deal) return;
    
    const init = async () => {
      const { data: { user } } = await supabase.auth.getUser();
      setUser(user);
      fetchReviews();
    };
    init();
  }, [isOpen, deal]);

  const fetchReviews = async () => {
    setLoadingReviews(true);
    const { data } = await supabase
      .from('reviews')
      .select('*, profiles(full_name)')
      .eq('deal_id', deal.id)
      .order('created_at', { ascending: false });
    
    if (data) setReviews(data);
    setLoadingReviews(false);
  };

  const handleReviewUpload = async (file: File) => {
    const fileExt = file.name.split('.').pop();
    const fileName = `${Math.random()}.${fileExt}`;
    const { error: uploadError } = await supabase.storage
      .from('review-images')
      .upload(fileName, file);

    if (uploadError) return null;
    const { data } = supabase.storage.from('review-images').getPublicUrl(fileName);
    return data.publicUrl;
  };

  const handleSubmitReview = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!user) return alert("Please sign in to leave a review.");
    setIsSubmitting(true);
    
    let uploadedImageUrl = null;
    if (reviewImage) {
      uploadedImageUrl = await handleReviewUpload(reviewImage);
    }
    
    const { error } = await supabase.from('reviews').insert([{
      deal_id: deal.id,
      user_id: user.id,
      rating,
      comment,
      image_url: uploadedImageUrl
    }]);

    setIsSubmitting(false);
    if (error) {
      alert("Error: " + error.message);
    } else {
      setComment('');
      setReviewImage(null);
      setRating(5);
      fetchReviews();
    }
  };

  if (!isOpen || !deal) return null;

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm overflow-y-auto">
      <div className="bg-white rounded-2xl w-full max-w-4xl shadow-2xl relative my-8 flex flex-col md:flex-row overflow-hidden">
        <button onClick={onClose} className="absolute top-4 right-4 z-10 p-2 bg-white/80 rounded-full hover:bg-white text-gray-700">
          <X className="w-5 h-5" />
        </button>

        {/* Left Side - Image & Main Details */}
        <div className="md:w-1/2 bg-gray-50 flex flex-col">
          <div className="relative h-64 md:h-80 w-full bg-gray-200">
            <Image src={deal.image_url || 'https://images.unsplash.com/photo-1556742049-0cfed4f6a45d?auto=format&fit=crop&q=80&w=800'} alt={deal.title} fill className="object-cover" />
            <div className="absolute bottom-4 left-4 bg-black/70 text-white px-3 py-1 rounded-full text-sm font-medium flex items-center gap-1 backdrop-blur-md">
              <MapPin className="w-4 h-4 text-green-400" /> {deal.location || 'Addis Ababa'}
            </div>
          </div>
          
          <div className="p-6">
            <h2 className="text-2xl font-bold text-gray-900 mb-2">{deal.title}</h2>
            <p className="text-gray-600 font-medium mb-6">{deal.merchant_name}</p>
            
            <div className="flex items-center justify-between p-4 bg-white rounded-xl shadow-sm border border-gray-100 mb-6">
              <div>
                <p className="text-sm text-gray-400 line-through">ETB {deal.original_price}</p>
                <p className="text-3xl font-black text-green-600">ETB {deal.discounted_price}</p>
              </div>
              <button onClick={() => { onClose(); onBuy(); }} className="bg-green-600 hover:bg-green-700 text-white font-bold py-3 px-8 rounded-xl transition-colors shadow-lg shadow-green-600/30">
                Buy Now
              </button>
            </div>
            
            <div className="space-y-4">
              {deal.description && (
                <div>
                  <h4 className="font-bold text-gray-900 mb-1">About This Deal</h4>
                  <p className="text-gray-600 text-sm whitespace-pre-line">{deal.description}</p>
                </div>
              )}
              {deal.highlights && (
                <div>
                  <h4 className="font-bold text-gray-900 mb-1">Highlights</h4>
                  <p className="text-gray-600 text-sm">{deal.highlights}</p>
                </div>
              )}
              {deal.fine_print && (
                <div>
                  <h4 className="font-bold text-gray-900 mb-1">The Fine Print</h4>
                  <p className="text-gray-500 text-xs">{deal.fine_print}</p>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Right Side - Reviews */}
        <div className="md:w-1/2 bg-white flex flex-col max-h-[80vh] overflow-y-auto">
          <div className="p-6 border-b sticky top-0 bg-white/95 backdrop-blur z-10">
            <h3 className="text-xl font-bold text-gray-900">Customer Reviews</h3>
          </div>
          
          <div className="p-6 space-y-6 flex-1">
            {/* Add Review Form */}
            {user ? (
              <form onSubmit={handleSubmitReview} className="bg-gray-50 p-4 rounded-xl border border-gray-100 space-y-3">
                <h4 className="font-bold text-sm text-gray-800">Write a Review</h4>
                <div className="flex gap-2">
                  {[1,2,3,4,5].map(star => (
                    <button key={star} type="button" onClick={() => setRating(star)} className={`hover:scale-110 transition-transform ${star <= rating ? 'text-yellow-400' : 'text-gray-300'}`}>
                      <Star className="w-6 h-6 fill-current" />
                    </button>
                  ))}
                </div>
                <textarea 
                  required
                  rows={2} 
                  value={comment}
                  onChange={e => setComment(e.target.value)}
                  placeholder="Share your experience..." 
                  className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-green-500 text-sm" 
                />
                <div className="flex items-center justify-between">
                  <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer hover:text-green-600">
                    <ImageIcon className="w-5 h-5" />
                    <span>{reviewImage ? reviewImage.name : 'Add Photo'}</span>
                    <input type="file" accept="image/*" className="sr-only" onChange={(e) => e.target.files && setReviewImage(e.target.files[0])} />
                  </label>
                  <button disabled={isSubmitting} type="submit" className="bg-gray-900 hover:bg-gray-800 text-white px-4 py-2 rounded-lg text-sm font-medium flex items-center">
                    {isSubmitting ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : null} Submit
                  </button>
                </div>
              </form>
            ) : (
              <div className="bg-green-50 text-green-800 p-4 rounded-xl text-sm text-center">
                Sign in to leave a review and upload photos!
              </div>
            )}

            {/* Reviews List */}
            <div className="space-y-4">
              {loadingReviews ? (
                <div className="flex justify-center py-8"><Loader2 className="w-6 h-6 animate-spin text-green-600" /></div>
              ) : reviews.length === 0 ? (
                <p className="text-gray-500 text-center py-8 text-sm">No reviews yet. Be the first to review!</p>
              ) : (
                reviews.map(review => (
                  <div key={review.id} className="border-b border-gray-100 pb-4">
                    <div className="flex items-center justify-between mb-2">
                      <span className="font-bold text-gray-900 text-sm">{review.profiles?.full_name || 'Anonymous User'}</span>
                      <div className="flex gap-1 text-yellow-400">
                        {[...Array(review.rating)].map((_, i) => <Star key={i} className="w-3 h-3 fill-current" />)}
                      </div>
                    </div>
                    <p className="text-gray-600 text-sm mb-3">{review.comment}</p>
                    {review.image_url && (
                      <div className="relative w-full h-32 rounded-lg overflow-hidden border border-gray-100">
                        <Image src={review.image_url} alt="Review photo" fill className="object-cover" />
                      </div>
                    )}
                  </div>
                ))
              )}
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}
