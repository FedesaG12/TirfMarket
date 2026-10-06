'use client';

import React, { useState, useEffect } from 'react';
import Header from '@/components/Header';
import DealCard from '@/components/DealCard';
import MpesaModal from '@/components/MpesaModal';
import { Utensils, Coffee, Bed, Sparkles, MonitorSmartphone, Car, Loader2 } from 'lucide-react';
import { useLanguage } from '@/context/LanguageContext';
import { supabase } from '@/lib/supabase';

export default function Home() {
  const [selectedDeal, setSelectedDeal] = useState<any | null>(null);
  const [deals, setDeals] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const { t } = useLanguage();

  useEffect(() => {
    const fetchDeals = async () => {
      const { data, error } = await supabase
        .from('deals')
        .select('*')
        .eq('status', 'approved')
        .order('created_at', { ascending: false });
      
      if (!error && data) {
        setDeals(data);
      }
      setLoading(false);
    };

    fetchDeals();
  }, []);

  const CATEGORIES = [
    { name: t('cat.food'), icon: Utensils, color: 'bg-orange-100 text-orange-600' },
    { name: t('cat.coffee'), icon: Coffee, color: 'bg-amber-100 text-amber-700' },
    { name: t('cat.spa'), icon: Sparkles, color: 'bg-purple-100 text-purple-600' },
    { name: t('cat.hotels'), icon: Bed, color: 'bg-blue-100 text-blue-600' },
    { name: t('cat.electronics'), icon: MonitorSmartphone, color: 'bg-gray-100 text-gray-700' },
    { name: t('cat.auto'), icon: Car, color: 'bg-red-100 text-red-600' },
  ];

  return (
    <div className="min-h-screen bg-gray-50 font-sans">
      <Header />
      
      <main className="container mx-auto px-4 py-8">
        {/* Hero Section */}
        <div className="bg-gradient-to-r from-green-800 via-green-700 to-yellow-600 rounded-3xl p-8 mb-12 text-white shadow-xl relative overflow-hidden">
          <div className="absolute top-0 right-0 w-64 h-64 bg-yellow-500 rounded-full opacity-20 blur-3xl -translate-y-1/2 translate-x-1/3"></div>
          <div className="absolute bottom-0 left-0 w-64 h-64 bg-red-500 rounded-full opacity-20 blur-3xl translate-y-1/2 -translate-x-1/3"></div>
          
          <div className="relative z-10 max-w-2xl">
            <h1 className="text-4xl md:text-5xl font-extrabold mb-4">
              {t("hero.title")}
            </h1>
            <p className="text-lg md:text-xl mb-8 text-green-50">
              {t("hero.subtitle")}
            </p>
            <div className="flex flex-wrap gap-4">
              <button className="bg-yellow-500 hover:bg-yellow-400 text-gray-900 font-bold py-3 px-8 rounded-full transition-colors shadow-lg">
                {t("hero.explore")}
              </button>
              <button className="bg-white/20 hover:bg-white/30 backdrop-blur-sm border border-white/40 text-white font-bold py-3 px-8 rounded-full transition-colors">
                {t("hero.how")}
              </button>
            </div>
          </div>
        </div>

        {/* Categories */}
        <div className="mb-12">
          <h2 className="text-2xl font-bold text-gray-900 mb-6 border-b-2 border-green-600 inline-block pb-1">{t("categories.title")}</h2>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
            {CATEGORIES.map((cat, idx) => (
              <div key={idx} className="bg-white rounded-xl p-4 flex flex-col items-center justify-center gap-3 cursor-pointer hover:shadow-md transition-shadow border border-gray-100">
                <div className={`p-3 rounded-full ${cat.color}`}>
                  <cat.icon className="w-6 h-6" />
                </div>
                <span className="text-sm font-medium text-gray-700 text-center">{cat.name}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Trending Deals */}
        <div>
          <div className="flex justify-between items-end mb-6">
            <h2 className="text-2xl font-bold text-gray-900 border-b-2 border-green-600 inline-block pb-1">{t("trending.title")}</h2>
            <button className="text-green-700 font-medium hover:underline text-sm">{t("trending.viewAll")}</button>
          </div>
          
          {loading ? (
            <div className="py-20 flex justify-center items-center">
              <Loader2 className="w-8 h-8 animate-spin text-green-600" />
            </div>
          ) : deals.length === 0 ? (
            <div className="py-20 text-center text-gray-500 bg-white rounded-xl border border-gray-100">
              No deals available at the moment. Check back soon!
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
              {deals.map((deal) => (
                <DealCard 
                  key={deal.id}
                  id={deal.id}
                  title={deal.title}
                  merchant={deal.merchant_name || 'TirfMarket Merchant'}
                  location="Addis Ababa" // Note: Currently hardcoded as we simplified
                  originalPrice={deal.original_price}
                  discountedPrice={deal.discounted_price}
                  image={deal.image_url}
                  bought={deal.bought_count || 0}
                  onBuy={() => setSelectedDeal(deal)}
                />
              ))}
            </div>
          )}
        </div>
      </main>

      {/* Footer */}
      <footer className="bg-gray-900 text-white pt-12 pb-8 mt-20">
        <div className="container mx-auto px-4">
          <div className="grid grid-cols-1 md:grid-cols-4 gap-8 mb-8 border-b border-gray-800 pb-8">
            <div>
              <h3 className="text-2xl font-bold mb-4 flex items-center gap-1">
                <span className="text-yellow-500">Tirf</span>Market
              </h3>
              <p className="text-gray-400 text-sm mb-4">
                The leading daily deal platform in Ethiopia. Discover, buy and share the best deals in your city.
              </p>
              <div className="flex gap-2">
                <div className="w-8 h-6 bg-green-600 rounded-sm"></div>
                <div className="w-8 h-6 bg-yellow-500 rounded-sm"></div>
                <div className="w-8 h-6 bg-red-600 rounded-sm"></div>
              </div>
            </div>
            <div>
              <h4 className="font-bold mb-4">Company</h4>
              <ul className="space-y-2 text-sm text-gray-400">
                <li><a href="#" className="hover:text-white">About Us</a></li>
                <li><a href="#" className="hover:text-white">Careers</a></li>
                <li><a href="#" className="hover:text-white">Press</a></li>
              </ul>
            </div>
            <div>
              <h4 className="font-bold mb-4">Work with Us</h4>
              <ul className="space-y-2 text-sm text-gray-400">
                <li><a href="#" className="hover:text-white">Run a Deal</a></li>
                <li><a href="#" className="hover:text-white">Merchant Center</a></li>
                <li><a href="#" className="hover:text-white">Affiliate Program</a></li>
              </ul>
            </div>
            <div>
              <h4 className="font-bold mb-4">Payment Partners</h4>
              <div className="bg-white rounded p-2 inline-block">
                <span className="text-green-600 font-bold tracking-wider">M-PESA</span>
              </div>
            </div>
          </div>
          <div className="text-center text-sm text-gray-500">
            &copy; {new Date().getFullYear()} TirfMarket. All rights reserved. Made in Ethiopia.
          </div>
        </div>
      </footer>

      {/* M-Pesa Payment Modal */}
      {selectedDeal && (
        <MpesaModal 
          isOpen={!!selectedDeal} 
          onClose={() => setSelectedDeal(null)} 
          amount={selectedDeal.discountedPrice}
          dealTitle={selectedDeal.title}
        />
      )}
    </div>
  );
}
