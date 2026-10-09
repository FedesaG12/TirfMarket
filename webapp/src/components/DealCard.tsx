import React from 'react';
import Image from 'next/image';
import { MapPin, Clock } from 'lucide-react';
import { useLanguage } from '@/context/LanguageContext';

interface DealProps {
  id: string;
  title: string;
  merchant: string;
  location: string;
  originalPrice: number;
  discountedPrice: number;
  image: string;
  bought: number;
  onBuy: () => void;
  onClick?: () => void;
}

export default function DealCard({ 
  title, 
  merchant, 
  location, 
  originalPrice, 
  discountedPrice, 
  image, 
  bought,
  onBuy,
  onClick
}: DealProps) {
  const safeOriginal = Number(originalPrice) || 0;
  const safeDiscounted = Number(discountedPrice) || 0;
  const discountPercent = safeOriginal > 0 ? Math.round(((safeOriginal - safeDiscounted) / safeOriginal) * 100) : 0;
  const { t } = useLanguage();

  return (
    <div onClick={onClick} className={`bg-white rounded-xl shadow-md overflow-hidden hover:shadow-lg transition-shadow duration-300 border border-gray-100 flex flex-col h-full ${onClick ? 'cursor-pointer' : ''}`}>
      <div className="relative h-48 w-full bg-gray-200">
        <Image 
          src={image} 
          alt={title} 
          fill
          className="object-cover"
        />
        <div className="absolute top-2 right-2 bg-red-600 text-white text-xs font-bold px-2 py-1 rounded-md">
          {discountPercent}% OFF
        </div>
      </div>
      
      <div className="p-4 flex flex-col flex-grow">
        <h3 className="font-bold text-gray-900 text-lg line-clamp-2 mb-1">{title}</h3>
        <p className="text-sm text-gray-500 mb-2">{merchant}</p>
        
        <div className="flex items-center text-xs text-gray-500 mb-4 gap-4">
          <span className="flex items-center gap-1"><MapPin className="w-3 h-3" /> {location}</span>
          <span className="flex items-center gap-1 text-green-700">{bought}+ {t("deal.bought")}</span>
        </div>
        
        <div className="mt-auto flex items-end justify-between pt-4 border-t border-gray-100">
          <div>
            <p className="text-sm text-gray-400 line-through">ETB {safeOriginal.toLocaleString()}</p>
            <p className="text-xl font-bold text-green-700">ETB {safeDiscounted.toLocaleString()}</p>
          </div>
          
          <button 
            onClick={(e) => { e.stopPropagation(); onBuy(); }}
            className="bg-green-600 hover:bg-green-700 text-white font-medium py-2 px-4 rounded-lg transition-colors flex items-center gap-2 text-sm"
          >
            {t("deal.buyNow")}
          </button>
        </div>
      </div>
    </div>
  );
}
