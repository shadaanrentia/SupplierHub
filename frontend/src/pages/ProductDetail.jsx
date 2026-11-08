import React from "react";
import {useParams,Link} from "react-router-dom";
import ProductDetails from "../components/ProductDetails";
export default function ProductDetail(){const {id}=useParams();return <><Link to="/products" className="block px-6 pt-4 text-sm text-blue-400">Back to products</Link><ProductDetails productId={id}/></>;}
